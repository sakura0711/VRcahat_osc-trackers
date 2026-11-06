// Runs the generated viewer logic with a small DOM/canvas model. No browser/network.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2], 'utf8');
const encoded = html.split('<script id="payload" type="application/json">')[1].split('</script>')[0];
const payload = JSON.parse(encoded);
assert.equal(payload.frames.length, 2);
const draws = [], arcs = [], images = [];
const context = {
  clearRect() {}, drawImage(image) { draws.push(image.id); }, beginPath() {}, moveTo() {}, lineTo() {},
  stroke() {}, arc(...args) { arcs.push(args); }, fill() {}, fillText() {},
};
class Element {
  constructor() { this.value = '0'; this.checked = false; this.children = []; this.textContent = ''; }
  replaceChildren() { this.children = []; }
  append(child) { this.children.push(child); }
  getContext() { return context; }
}
const elements = Object.fromEntries(['payload', 'image', 'frame', 'overlay', 'indices', 'identity', 'details', 'points', 'tracker', 'previous', 'next'].map(name => [name, new Element()]));
elements.payload.textContent = encoded;
elements.overlay.checked = true;
class Image {
  constructor() { this.id = images.length; images.push(this); }
  set src(value) { this.source = value; }
}
const sandbox = {document: {getElementById: id => elements[id], createElement: () => new Element()}, Image};
vm.runInNewContext(html.split('<script>').at(-1).split('</script>')[0], sandbox, {timeout: 1000});
// Change frame before the first asynchronous image load completes.
elements.frame.value = '1';
elements.frame.oninput();
images[1].onload();
assert.deepEqual(draws, [1]);
assert.equal(elements.image.width, 3);
assert.equal(elements.image.height, 2);
assert.equal(arcs[27][0], 2.25); // x=.75, no extra mirror despite mirroredInput=true.
assert.equal(arcs[27][1], .5);  // y=.25, original full-frame dimensions.
assert.ok(elements.identity.textContent.includes('影格 12'));
const count = arcs.length;
images[0].onload();
assert.deepEqual(draws, [1]);
assert.equal(arcs.length, count);
assert.ok(elements.identity.textContent.includes('影格 12'));
elements.overlay.checked = false;
elements.overlay.onchange();
images[2].onload();
assert.equal(arcs.length, count);
assert.equal(elements.points.children.length, 10);
console.log('Viewer logic verified: full-image coordinates, no double mirror, stale image load rejected and overlay toggle.');
