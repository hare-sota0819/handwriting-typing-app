// Render LaTeX equations to SVG via MathJax (mathjax-full v3, direct API).
// Reads spike/out/equations.json ([{id, latex, display}]), writes
// spike/out/svg/<id>.svg. Spike-quality tool.
//
// Run: node spike/tex2svg.js

const fs = require('fs');
const path = require('path');

const { mathjax } = require('mathjax-full/js/mathjax.js');
const { TeX } = require('mathjax-full/js/input/tex.js');
const { SVG } = require('mathjax-full/js/output/svg.js');
const { liteAdaptor } = require('mathjax-full/js/adaptors/liteAdaptor.js');
const { RegisterHTMLHandler } = require('mathjax-full/js/handlers/html.js');
const { AllPackages } = require('mathjax-full/js/input/tex/AllPackages.js');

// HW_MATH_OUT overrides the working dir (the document pipeline keeps its own,
// so it never clobbers the equation-sheet run the GUI may have cached).
const OUT_ROOT = process.env.HW_MATH_OUT || path.join(__dirname, 'out');
const OUT = path.join(OUT_ROOT, 'svg');
fs.mkdirSync(OUT, { recursive: true });

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);

const equations = JSON.parse(
  fs.readFileSync(path.join(OUT_ROOT, 'equations.json'), 'utf8'));

for (const eq of equations) {
  // Fresh document per equation so <defs> ids and font cache don't leak
  // across files (fontCache: 'local' keeps each SVG self-contained).
  const tex = new TeX({ packages: AllPackages });
  const svg = new SVG({ fontCache: 'local' });
  const doc = mathjax.document('', { InputJax: tex, OutputJax: svg });
  const node = doc.convert(eq.latex, { display: eq.display !== false });
  const svgNode = adaptor.firstChild(node);
  const out = adaptor.outerHTML(svgNode);
  fs.writeFileSync(path.join(OUT, `${eq.id}.svg`), out);
  console.log(`${eq.id}: ${out.length} bytes`);
}
console.log(`mathjax-full ${require('mathjax-full/package.json').version}`);
