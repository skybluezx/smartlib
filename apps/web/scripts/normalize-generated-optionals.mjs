// @hey-api 0.99 emits optional properties that are assigned explicit undefined.
// Preserve strict project checking by spelling out that runtime contract, reproducibly.
import ts from 'typescript';
import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import { resolve, join } from 'node:path';
export function normalizeGeneratedOptionals(root) {
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const file = join(root, entry.name);
    if (entry.isDirectory()) { normalizeGeneratedOptionals(file); continue; }
    if (!file.endsWith('.ts')) continue;
    let text = readFileSync(file, 'utf8');
    const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
    const edits = [];
    function visit(node) {
      if (ts.isPropertySignature(node) && node.questionToken && node.type && !node.type.getText(source).includes('undefined')) edits.push({pos: node.type.getStart(source), text: '('}, {pos: node.type.end, text: ') | undefined'});
      ts.forEachChild(node, visit);
    }
    visit(source);
    for (const edit of edits.sort((a, b) => b.pos - a.pos)) text = text.slice(0, edit.pos) + edit.text + text.slice(edit.pos);
    if (file.endsWith('/client/client.gen.ts') || file.endsWith('/core/serverSentEvents.gen.ts')) {
      const source2 = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
      const wraps = [];
      function wrap(node) {
        if (ts.isVariableDeclaration(node) && node.name.getText(source2) === 'requestInit' && node.initializer) {
          wraps.push({pos: node.initializer.getStart(source2), text: 'omitUndefined('}, {pos: node.initializer.end, text: ')'});
        }
        if (ts.isCallExpression(node) && node.expression.getText(source2) === 'createSseClient' && node.arguments[0]) {
          wraps.push({pos: node.arguments[0].getStart(source2), text: 'omitUndefined('}, {pos: node.arguments[0].end, text: ')'});
        }
        ts.forEachChild(node, wrap);
      }
      wrap(source2);
      for (const edit of wraps.sort((a,b)=>b.pos-a.pos)) text=text.slice(0,edit.pos)+edit.text+text.slice(edit.pos);
      text = text.replace('onRequest: async (url, init)', 'onRequest: async (url: string, init: RequestInit)');
      text += `
type Defined<T> = { [K in keyof T as undefined extends T[K] ? never : K]: T[K] } & { [K in keyof T as undefined extends T[K] ? K : never]?: Exclude<T[K], undefined> };
function omitUndefined<const T extends object>(value: T): Defined<T> {
  return Object.fromEntries(Object.entries(value).filter(([,v]) => v !== undefined)) as Defined<T>;
}
`;
    }
    writeFileSync(file, text);
  }
}
if (process.argv[1] && resolve(process.argv[1]) === import.meta.filename) normalizeGeneratedOptionals(resolve(process.argv[2] ?? 'src/generated/smartlib-api'));
