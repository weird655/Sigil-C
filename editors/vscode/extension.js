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
}

function deactivate() {
    if (proc) { proc.kill(); proc = null; }
}

module.exports = { activate, deactivate };
