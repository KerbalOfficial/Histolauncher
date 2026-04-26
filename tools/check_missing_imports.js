const fs = require('fs');
const path = require('path');

const DIR = path.resolve(__dirname, '..', 'src', 'ui', 'modules');

const filesByExport = {};
const addExport = (name, f) => {
  if (!name) return;
  if (!filesByExport[name]) filesByExport[name] = new Set();
  filesByExport[name].add(f);
};
for (const f of fs.readdirSync(DIR)) {
  if (!f.endsWith('.js')) continue;
  const t = fs.readFileSync(path.join(DIR, f), 'utf8');
  let m;
  const re = /^export\s+(?:const|let|async\s+function|function|class)\s+([A-Za-z_$][\w$]*)/gm;
  while ((m = re.exec(t))) addExport(m[1], f);
  const re2 = /^export\s*\{([^}]+)\}/gm;
  while ((m = re2.exec(t))) {
    m[1].split(',').forEach((n) => addExport(n.trim().split(/\s+as\s+/).pop().trim(), f));
  }
}
const allExports = Object.keys(filesByExport);

let problems = 0;
for (const f of fs.readdirSync(DIR)) {
  if (!f.endsWith('.js')) continue;
  const src = fs.readFileSync(path.join(DIR, f), 'utf8');

  const imported = new Set();
  let m;
  const ir = /import\s*\{([^}]+)\}\s*from/g;
  while ((m = ir.exec(src))) {
    m[1].split(',').forEach((p) => {
      const nm = p.trim().split(/\s+as\s+/).pop().trim();
      if (nm) imported.add(nm);
    });
  }
  const ir2 = /import\s+([A-Za-z_$][\w$]*)\s+from/g;
  while ((m = ir2.exec(src))) imported.add(m[1]);

  const local = new Set();
  const lr = /(?:^|\n)\s*(?:export\s+)?(?:const|let|var|async\s+function|function|class)\s+([A-Za-z_$][\w$]*)/g;
  while ((m = lr.exec(src))) local.add(m[1]);

  let stripped = src.replace(/^import[^;]+;/gm, '');
  stripped = (() => {
    const s = stripped;
    let out = '';
    let i = 0;
    const n = s.length;
    while (i < n) {
      const c = s[i], c2 = s[i + 1];
      if (c === '/' && c2 === '/') { while (i < n && s[i] !== '\n') i++; continue; }
      if (c === '/' && c2 === '*') { i += 2; while (i < n - 1 && !(s[i] === '*' && s[i + 1] === '/')) i++; i += 2; continue; }
      if (c === '\'' || c === '"') {
        const q = c; i++;
        while (i < n && s[i] !== q) { if (s[i] === '\\') i += 2; else i++; }
        i++; out += '""'; continue;
      }
      if (c === '`') {
        i++;
        while (i < n && s[i] !== '`') {
          if (s[i] === '\\') { i += 2; continue; }
          if (s[i] === '$' && s[i + 1] === '{') {
            i += 2;
            let depth = 1;
            while (i < n && depth > 0) {
              const ch = s[i];
              if (ch === '{') depth++;
              else if (ch === '}') { depth--; if (depth === 0) break; }
              out += ch; i++;
            }
            i++; continue;
          }
          i++;
        }
        i++; continue;
      }
      out += c; i++;
    }
    return out;
  })();

  for (const name of allExports) {
    if (imported.has(name) || local.has(name)) continue;
    if (filesByExport[name].has(f)) continue;
    const esc = name.replace(/\$/g, '\\$');
    const usageRe = new RegExp(`(?<![\\w$])(?<!(?<!\\.)\\.)${esc}(?![\\w$])`, 'g');
    if (usageRe.test(stripped)) {
      const owners = [...filesByExport[name]].join(', ');
      console.log(`${f}: uses '${name}' (exported by ${owners}) but does not import or declare it`);
      problems++;
    }
  }
}

console.log(problems === 0 ? '\nNo missing-import problems found.' : `\n${problems} potential missing-import problems.`);