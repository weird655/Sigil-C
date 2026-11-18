const vscode = require('vscode');
const cp = require('child_process');
const fs = require('fs');
const path = require('path');

let proc = null;
let buf = Buffer.alloc(0);
let collection = null;
let output = null;
let started = false;
let nextId = 1;

function config() {
    const cfg = vscode.workspace.getConfiguration('sigilC');
    return {
        python: cfg.get('pythonPath', '') || (process.platform === 'win32' ? 'python' : 'python3'),
        cli: cfg.get('cliPath', 'sigilc.py'),
        diagnostics: cfg.get('diagnostics', true)
    };
}

function cliPath() {
    const c = config();
    if (path.isAbsolute(c.cli)) return c.cli;
    const root = vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0];
    return root ? path.join(root.uri.fsPath, c.cli) : c.cli;
}

function send(msg) {
    if (!proc) return;
    const body = JSON.stringify(msg);
    proc.stdin.write(`Content-Length: ${Buffer.byteLength(body)}\r\n\r\n${body}`);
}

function handle(msg) {
    if (msg.method === 'textDocument/publishDiagnostics' && collection) {
        const diags = (msg.params.diagnostics || []).map(d => {
            const sev = d.severity === 2 ? vscode.DiagnosticSeverity.Warning
                : d.severity === 3 ? vscode.DiagnosticSeverity.Information
                    : vscode.DiagnosticSeverity.Error;
            const diag = new vscode.Diagnostic(
                new vscode.Range(d.range.start.line, d.range.start.character,
                    d.range.end.line, d.range.end.character),
                d.message, sev);
            diag.source = d.source || 'sigil-c';
            return diag;
        });
        collection.set(vscode.Uri.parse(msg.params.uri), diags);
    }
}

function onData(chunk) {
    buf = Buffer.concat([buf, chunk]);
    for (;;) {
        const sep = buf.indexOf('\r\n\r\n');
        if (sep < 0) return;
        const header = buf.slice(0, sep).toString('ascii');
        const m = /Content-Length:\s*(\d+)/i.exec(header);
        if (!m) {
            buf = buf.slice(sep + 4);
            continue;
        }
        const len = parseInt(m[1], 10);
        if (buf.length < sep + 4 + len) return;
        const body = buf.slice(sep + 4, sep + 4 + len).toString('utf8');
        buf = buf.slice(sep + 4 + len);
        try { handle(JSON.parse(body)); } catch (e) { output.appendLine(`sigil-c LSP parse: ${e}`); }
    }
}

function start(context) {
    if (proc) return;
    const c = config();
    const root = vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0];
    const cwd = root ? root.uri.fsPath : process.cwd();
    try {
        proc = cp.spawn(c.python, [cliPath(), '--lsp'], { cwd });
    } catch (e) {
        output.appendLine(`spawn failed: ${e}`);
        return;
    }
    proc.stdout.on('data', onData);
    proc.stderr.on('data', d => output.append(d.toString()));
    proc.on('exit', code => {
        output.appendLine(`sigil-c LSP exited: ${code}`);
        proc = null;
        started = false;
    });
    send({
        jsonrpc: '2.0', id: nextId++, method: 'initialize',
        params: {
            processId: process.pid,
            rootUri: root ? root.uri.toString() : null,
            capabilities: {
                textDocument: { synchronization: { dynamicRegistration: false } }
            }
        }
    });
    send({ jsonrpc: '2.0', method: 'initialized', params: {} });
    started = true;
    for (const doc of vscode.workspace.textDocuments) {
        if (doc.languageId === 'sigil') open(doc);
    }
}

function open(doc) {
    if (!proc) return;
    send({
        jsonrpc: '2.0', method: 'textDocument/didOpen',
        params: {
            textDocument: {
                uri: doc.uri.toString(), languageId: 'sigil',
                version: doc.version, text: doc.getText()
            }
        }
    });
}

function change(doc) {
    if (!proc) return;
    send({
        jsonrpc: '2.0', method: 'textDocument/didChange',
        params: {
            textDocument: { uri: doc.uri.toString(), version: doc.version },
            contentChanges: [{ text: doc.getText() }]
        }
    });
}

function runCLI(args, cwd) {
    return new Promise((resolve, reject) => {
        const c = config();
        const p = cp.spawn(c.python, [cliPath(), ...args], { cwd });
        let out = '';
        let err = '';
        p.stdout.on('data', d => { out += d; output.append(d.toString()); });
        p.stderr.on('data', d => { err += d; output.append(d.toString()); });
        p.on('error', reject);
        p.on('close', code => resolve({ code, out, err }));
    });
}

function activeSigilDoc() {
    const doc = vscode.window.activeTextEditor && vscode.window.activeTextEditor.document;
    return doc && doc.languageId === 'sigil' ? doc : null;
}

function workspaceRoot() {
    const folders = vscode.workspace.workspaceFolders;
    return folders && folders.length ? folders[0].uri.fsPath : undefined;
}

async function checkActive() {
    const doc = activeSigilDoc();
    if (!doc) { vscode.window.showWarningMessage('Sigil-C: open a .sigil file first'); return; }
    await doc.save();
    output.show(true);
    const r = await runCLI(['--check', '--json', doc.uri.fsPath], workspaceRoot());
    try {
        const data = JSON.parse(r.out);
        const diags = (data.diagnostics || []).map(d => {
            const line = Math.max(0, (d.line || 1) - 1);
            const col = Math.max(0, (d.column || 1) - 1);
            const sev = d.severity === 'warning' ? vscode.DiagnosticSeverity.Warning : vscode.DiagnosticSeverity.Error;
            const diag = new vscode.Diagnostic(new vscode.Range(line, col, line, col + 1), d.message, sev);
            diag.source = 'sigil-c';
            return diag;
        });
        collection.set(doc.uri, diags);
        if (!r.code) { vscode.window.showInformationMessage(`Sigil-C: ${data.checked || 1} file(s) OK`); }
    } catch (e) {
        vscode.window.showErrorMessage('Sigil-C check failed; see output');
    }
}

async function formatActive() {
    const doc = activeSigilDoc();
    if (!doc) { vscode.window.showWarningMessage('Sigil-C: open a .sigil file first'); return; }
    await doc.save();
    output.show(true);
    const r = await runCLI(['--fmt', '--write', doc.uri.fsPath], workspaceRoot());
    if (r.code === 0) { vscode.window.showInformationMessage('Sigil-C: formatted'); }
    else { vscode.window.showErrorMessage('Sigil-C: format failed; see output'); }
}

function buildWorkspace() {
    const root = workspaceRoot();
    if (!root) { vscode.window.showWarningMessage('Sigil-C: open a workspace folder first'); return; }
    const c = config();
    const term = vscode.window.createTerminal({ name: 'Sigil-C build', cwd: root });
    term.show(true);
    term.sendText(`"${c.python}" "${cliPath()}" --build "${root}"`);
}

function activate(context) {
    collection = vscode.languages.createDiagnosticCollection('sigil-c');
    output = vscode.window.createOutputChannel('Sigil-C');
    context.subscriptions.push(collection, output);
    start(context);
    context.subscriptions.push(vscode.workspace.onDidOpenTextDocument(doc => {
        if (doc.languageId === 'sigil') open(doc);
    }));
    context.subscriptions.push(vscode.workspace.onDidChangeTextDocument(ev => {
        if (ev.document.languageId === 'sigil') change(ev.document);
    }));
    context.subscriptions.push(vscode.workspace.onDidCloseTextDocument(doc => {
        if (doc.languageId === 'sigil' && proc) {
            send({ jsonrpc: '2.0', method: 'textDocument/didClose', params: { textDocument: { uri: doc.uri.toString() } } });
            collection.delete(doc.uri);
        }
    }));
    context.subscriptions.push(vscode.workspace.onDidChangeConfiguration(ev => {
        if (ev.affectsConfiguration('sigilC')) {
            if (proc) { proc.kill(); proc = null; }
            start(context);
        }
    }));
    context.subscriptions.push(vscode.commands.registerCommand('sigilC.checkFile', checkActive));
    context.subscriptions.push(vscode.commands.registerCommand('sigilC.formatFile', formatActive));
    context.subscriptions.push(vscode.commands.registerCommand('sigilC.buildWorkspace', buildWorkspace));
    context.subscriptions.push(vscode.commands.registerCommand('sigilC.showOutput', () => output.show(true)));
    context.subscriptions.push(vscode.commands.registerCommand('sigilC.restartServer', () => {
        if (proc) { proc.kill(); proc = null; }
        start(context);
    }));
}

function deactivate() {
    if (proc) { proc.kill(); proc = null; }
}

module.exports = { activate, deactivate };
