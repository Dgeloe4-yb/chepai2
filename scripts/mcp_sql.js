#!/usr/bin/env node
/** One-shot MCP MySQL client (newline JSON-RPC, same protocol as Cursor MCP). */
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const MCP_JSON = path.join(ROOT, ".cursor", "mcp.json");
const cfg = JSON.parse(fs.readFileSync(MCP_JSON, "utf8")).mcpServers.mysql;

const SERVER = cfg.args[0];
const env = { ...process.env, ...cfg.env };

function send(proc, msg) {
  proc.stdin.write(JSON.stringify(msg) + "\n");
}

function readResponses(proc, onMessage, done) {
  let buf = "";
  proc.stdout.on("data", (chunk) => {
    buf += chunk.toString();
    let idx;
    while ((idx = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, idx).trim();
      buf = buf.slice(idx + 1);
      if (!line) continue;
      try {
        onMessage(JSON.parse(line));
      } catch (e) {
        console.error("bad json:", line);
      }
    }
  });
  proc.on("close", (code) => done(code));
}

async function main() {
  const statements = process.argv.slice(2);
  if (statements.length === 0) {
    console.error("Usage: node mcp_sql.js \"SQL1\" \"SQL2\" ...");
    process.exit(1);
  }

  const proc = spawn(cfg.command, [SERVER], { env, stdio: ["pipe", "pipe", "inherit"] });
  const pending = new Map();
  let nextId = 1;

  readResponses(
    proc,
    (msg) => {
      if (msg.id != null && pending.has(msg.id)) {
        const { resolve, reject } = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message || JSON.stringify(msg.error)));
        else resolve(msg.result);
      }
    },
    (code) => {
      if (code !== 0) process.exit(code ?? 1);
    }
  );

  function call(method, params) {
    const id = nextId++;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      send(proc, { jsonrpc: "2.0", id, method, params });
    });
  }

  async function sqlQuery(sql) {
    const wrapped = await call("tools/call", {
      name: "sql_query",
      arguments: { sql },
    });
    const text = wrapped?.content?.[0]?.text;
    return text ? JSON.parse(text) : wrapped;
  }

  await call("initialize", {
    protocolVersion: "2025-06-18",
    capabilities: {},
    clientInfo: { name: "mcp_sql", version: "1.0.0" },
  });
  send(proc, { jsonrpc: "2.0", method: "notifications/initialized", params: {} });
  await new Promise((r) => setTimeout(r, 800));

  for (const sql of statements) {
    console.log("\n>>>", sql);
    const result = await sqlQuery(sql);
    console.log(JSON.stringify(result, null, 2));
  }

  send(proc, { jsonrpc: "2.0", id: nextId, method: "shutdown", params: {} });
  proc.stdin.end();
  await new Promise((r) => setTimeout(r, 500));
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
