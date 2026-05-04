const fs = require('fs');
const glob = require('fs').readdirSync;
const path = require('path');

const traverseDirs = (dir, ext) => {
    let results = [];
    glob(dir).forEach(file => {
        file = path.join(dir, file);
        const stat = fs.statSync(file);
        if (stat && stat.isDirectory()) { 
            if (!file.includes('vendor')) {
                results = results.concat(traverseDirs(file, ext));
            }
        } else if (file.endsWith(ext)) {
            results.push(file);
        }
    });
    return results;
};

const htmlFiles = traverseDirs('src/ui', '.html');
const jsFiles = traverseDirs('src/ui', '.js');

const keys = new Set();

const htmlRegex = /data-i18n(?:-[a-z]+)?="([^"]+)"/g;
htmlFiles.forEach(file => {
    const content = fs.readFileSync(file, 'utf8');
    let match;
    while ((match = htmlRegex.exec(content)) !== null) {
        keys.add(match[1]);
    }
});

const jsRegex = /(?<![\w])t\(['"]([^'"]+)['"]\)/g;
jsFiles.forEach(file => {
    const content = fs.readFileSync(file, 'utf8');
    let match;
    while ((match = jsRegex.exec(content)) !== null) {
        keys.add(match[1]);
    }
});

const sortedKeys = Array.from(keys).sort();

const constructObj = (keys) => {
    const obj = {};
    keys.forEach(k => {
        const parts = k.split('.');
        let current = obj;
        for (let i = 0; i < parts.length - 1; i++) {
            if (!current[parts[i]]) current[parts[i]] = {};
            current = current[parts[i]];
        }
        current[parts[parts.length - 1]] = k;
    });
    return obj;
};

const res = constructObj(sortedKeys);
fs.writeFileSync('src/ui/i18n/en.json', JSON.stringify(res, null, 2));
fs.writeFileSync('src/ui/i18n/es.json', JSON.stringify(res, null, 2));
console.log('Created en.json and es.json');
