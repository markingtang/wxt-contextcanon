// Real official SDK session plus the official Inspector CLI. Synthetic data only.
import {createRequire} from 'node:module';
import {mkdtempSync, mkdirSync, writeFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve, join, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import assert from 'node:assert/strict';

const prefix = resolve(process.argv[2] || '.mcp-test');
const require = createRequire(join(prefix, 'package.json'));
const {Client} = require('@modelcontextprotocol/client');
const {StdioClientTransport} = require('@modelcontextprotocol/client/stdio');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const home = mkdtempSync(join(tmpdir(), 'contextcanon-mcp-client-'));
const python = process.env.CONTEXTCANON_TEST_PYTHON || 'python';
const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('WXT_CONTEXTCANON_')));
Object.assign(env, {HOME: home, USERPROFILE: home, PYTHONPATH: join(root, 'packages'), PYTHONIOENCODING: 'utf-8'});
const server = {command: python, args: ['-m', 'contextcanon_cli', 'mcp'], cwd: home, env};
const results = [];
try {
  const seed = spawnSync(python, ['-m', 'contextcanon_cli', 'demo', 'seed', '--reset'], {cwd: home, env, encoding: 'utf8'});
  assert.equal(seed.status, 0, seed.stderr);
  for (const mode of ['legacy', 'auto']) {
    const client = new Client({name: 'contextcanon-synthetic-check', version: '0.1.2'}, {versionNegotiation: {mode}});
    const transport = new StdioClientTransport(server);
    const sent = [];
    const send = transport.send.bind(transport);
    transport.send = message => { if (message.method) sent.push(message.method); return send(message); };
    try {
      await client.connect(transport);
      assert.ok(sent.includes('initialize'));
      const tools = (await client.listTools()).tools.map(t => t.name).sort();
      assert.deepEqual(tools, ['profile_as_of','profile_audit','profile_get','profile_history','profile_search','profile_upsert','registry_event','registry_query']);
      const call = async (name, args) => {
        const result = await client.callTool({name, arguments: args});
        assert.equal(result.isError, false, JSON.stringify(result));
        return JSON.parse(result.content[0].text);
      };
      assert.equal((await call('profile_get', {subject:'demo:alex-chen',key:'tooling.editor'})).fact.value, 'zed');
      await call('profile_upsert', {subject:'demo:client',key:mode,value: {synthetic:true,number:42},source:'synthetic-client'});
      assert.equal((await call('profile_get', {subject:'demo:client',key:mode})).fact.value.number,42);
      assert.deepEqual((await call('profile_history', {subject:'demo:alex-chen',key:'tooling.editor'})).facts.map(f=>f.value),['vscode','zed']);
      const past = new Date(Date.now()-30*86400000).toISOString();
      assert.equal((await call('profile_as_of', {subject:'demo:alex-chen',timestamp:past})).facts.find(f=>f.key==='tooling.editor').value,'vscode');
      assert.equal((await client.callTool({name:'profile_get',arguments:{subject:42}})).isError,true);
      await client.ping();
      assert.equal((await client.listTools()).tools.length,8);
      results.push({client:'official SDK 2.3.1',mode,status:'PASS',checks:['initialize','8 tools','read','JSON write','history','as-of','bad-call then ping']});
    } finally { await client.close(); }
  }
  // Inspector CLI uses its actual connection and validation implementation.
  const config = join(home,'mcp.json');
  writeFileSync(config, JSON.stringify({mcpServers:{synthetic:server}}));
  const inspector = join(prefix,'node_modules','@modelcontextprotocol','inspector','clients','launcher','dist','index.js');
  // Resolve the published bin rather than depending on the layout above.
  const pkg = require(join(prefix,'node_modules','@modelcontextprotocol','inspector','package.json'));
  const bin = resolve(prefix,'node_modules','@modelcontextprotocol','inspector', typeof pkg.bin === 'string' ? pkg.bin : Object.values(pkg.bin)[0]);
  const base = [bin,'--cli','--config',config,'--server','synthetic','--protocol-era','auto','--format','json'];
  for (const args of [
    ['--method','tools/list','--strict'],
    ['--method','tools/call','--tool-name','profile_get','--tool-args-json',JSON.stringify({subject:'demo:alex-chen',key:'tooling.editor'})],
    ['--method','tools/call','--tool-name','profile_upsert','--tool-args-json',JSON.stringify({subject:'demo:inspector',key:'probe',value:42})],
    ['--method','tools/call','--tool-name','profile_history','--tool-args-json',JSON.stringify({subject:'demo:inspector',key:'probe'})],
    ['--method','tools/call','--tool-name','profile_get','--tool-args-json',JSON.stringify({subject:42})],
  ]) {
    const proc = spawnSync(process.execPath,[...base,...args],{env,cwd:home,encoding:'utf8',timeout:60000});
    const bad = args.at(-1) === JSON.stringify({subject:42});
    assert.ok(proc.status === 0 || (bad && proc.status !== null), proc.stderr || proc.stdout);
    const output = JSON.parse(proc.stdout);
    const body = JSON.stringify(output);
    if (bad) assert.ok(body.includes('isError') && body.includes('true'),body);
    else if (args.includes('tools/list')) assert.ok(body.includes('profile_upsert'),body);
    else if (args.includes('profile_get')) assert.ok(body.includes('zed'),body);
    else assert.ok(body.includes('42'),body);
    results.push({client:'Inspector 2.9.0',method:args[1],tool:args[3],negative:bad,status:'PASS'});
  }
  console.log(JSON.stringify(results,null,2));
} finally {
  rmSync(home,{recursive:true,force:true}); // only this invocation's mkdtemp tree
}
