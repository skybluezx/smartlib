import { normalizeGeneratedOptionals } from './normalize-generated-optionals.mjs';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative, resolve } from 'node:path';
import process from 'node:process';

const projectRoot = resolve(import.meta.dirname, '..');
const generatedRoot = resolve(projectRoot, 'src/generated/smartlib-api');
const temporaryRoot = mkdtempSync(join(tmpdir(), 'smartlib-openapi-'));
const temporaryOutput = join(temporaryRoot, 'smartlib-api');

function snapshot(root) {
  const files = [];
  const walk = (directory) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) walk(path);
      else files.push([relative(root, path), readFileSync(path, 'utf8')]);
    }
  };
  walk(root);
  return files.sort(([left], [right]) => left.localeCompare(right));
}

try {
  execFileSync(resolve(projectRoot, 'node_modules/.bin/openapi-ts'), [
    '--input', resolve(projectRoot, '../../packages/api-contracts/openapi/smartlib-platform-v1.json'),
    '--output', temporaryOutput,
    '--silent',
  ], { cwd: projectRoot, stdio: 'inherit' });

  normalizeGeneratedOptionals(temporaryOutput);
  if (JSON.stringify(snapshot(generatedRoot)) !== JSON.stringify(snapshot(temporaryOutput))) {
    console.error('Generated SmartLib API client has drifted. Run npm run generate:api.');
    process.exitCode = 1;
  } else {
    console.log('Generated SmartLib API client matches the committed OpenAPI contract.');
  }
} finally {
  rmSync(temporaryRoot, { recursive: true, force: true });
}
