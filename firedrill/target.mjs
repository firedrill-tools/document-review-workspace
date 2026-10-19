import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve, join } from 'node:path';
import { ApplicationError, commandMain, invokeCLI, privateDirectory } from './adapter-runtime.mjs';
const root = fileURLToPath(new URL('../', import.meta.url));
const backend = existsSync(join(root, 'backend/pyproject.toml')) ? join(root, 'backend') : root;
const cases = new Set(JSON.parse(readFileSync(join(backend, 'data/manifest.json'))).cases.map(item => item.id));
const requestDriver = fileURLToPath(new URL('./request.py', import.meta.url));
export async function runApplication(input, parameters, signal, invocation) {
  if (Object.keys(input).some(key => !['caseId', 'action', 'recordId', 'message'].includes(key)) || !cases.has(input.caseId) || !['chat', 'inspect'].includes(input.action) ||
      typeof input.recordId !== 'string' || !/^[A-Za-z0-9_-]{1,80}$/.test(input.recordId) ||
      (input.action === 'chat' ? typeof input.message !== 'string' || !input.message.trim() || input.message.length > 8000 || input.message.includes('\0') : input.message !== null)) throw new Error('Supply a reviewed case, exact document and chat message or explicit model-free inspection.');
  const directory = await privateDirectory(root, invocation), state = join(directory, 'workspace.json');
  const cli = ['uv', 'run', '--locked', '--no-sync'];
  try {
    await invokeCLI([...cli, 'document-review-api', '--init-case', input.caseId, '--workspace', state], { cwd: backend, signal });
    const argv = [...cli, 'python', requestDriver, '--workspace', state, '--action', input.action, '--record', input.recordId];
    if (input.action === 'chat') argv.push('--message', input.message);
    const env = { ...process.env, ...(parameters.model ? { ANTHROPIC_MODEL: parameters.model } : {}) };
    return { application: await invokeCLI(argv, { cwd: backend, signal, env }), localState: { directory, workspaceFile: state } };
  } catch (error) { if (error instanceof ApplicationError) error.evidence.runDirectory = directory; throw error; }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await commandMain(runApplication);
