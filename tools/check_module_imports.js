const fs = require('fs');
const path = require('path');
const target = path.resolve(process.argv[2]);
const src = fs.readFileSync(target, 'utf8');
const imps = new Set();
let m;
const ir = /import\s*\{([^}]+)\}\s*from/g;
while ((m = ir.exec(src))) m[1].split(',').forEach((p) => imps.add(p.trim().split(/\s+as\s+/).pop().trim()));

const dir = path.dirname(target);
const moduleExports = {};
for (const f of fs.readdirSync(dir)) {
  if (!f.endsWith('.js') || path.resolve(dir, f) === target) continue;
  const text = fs.readFileSync(path.join(dir, f), 'utf8');
  const re = /^export\s+(?:const|let|async\s+function|function|class)\s+([A-Za-z_$][\w$]*)/gm;
  while ((m = re.exec(text))) {
    if (!moduleExports[m[1]]) moduleExports[m[1]] = f;
  }
  const re2 = /^export\s*\{([^}]+)\}/gm;
  while ((m = re2.exec(text))) {
    m[1].split(',').forEach((n) => {
      const nm = n.trim().split(/\s+as\s+/).pop().trim();
      if (nm && !moduleExports[nm]) moduleExports[nm] = f;
    });
  }
}

const stripped = src
  .replace(/^import\s+[^;]+;/gm, '')
  .replace(/^export\s+\{[^}]+\}\s*from[^;]+;/gm, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/\/\/[^\n]*/g, '')
  .replace(/`(?:\\.|\$\{[^}]*\}|[^`\\])*`/g, '""')
  .replace(/'(?:\\.|[^'\\])*'/g, '""')
  .replace(/"(?:\\.|[^"\\])*"/g, '""')
  .replace(/(^|[=(,;:!&|?+\-*/%<>{}\[\]\n])\s*\/(?:\\.|\[(?:\\.|[^\]\\])*\]|[^/\\\n])+\/[gimsuy]*/g, '$1');

const tokens = new Set();
const tokRe = /(?<![.\w$])([A-Za-z_$][\w$]*)(?![\w$])/g;
while ((m = tokRe.exec(stripped))) tokens.add(m[1]);

const missing = {};
for (const t of tokens) {
  if (imps.has(t)) continue;
  if (moduleExports[t]) {
    if (!missing[moduleExports[t]]) missing[moduleExports[t]] = [];
    missing[moduleExports[t]].push(t);
  }
}
console.log(`\nFile: ${target}`);
if (Object.keys(missing).length === 0) console.log('  No missing module imports found.');
for (const [mod, names] of Object.entries(missing)) {
  console.log(`  Missing from ${mod}: ${names.join(', ')}`);
}