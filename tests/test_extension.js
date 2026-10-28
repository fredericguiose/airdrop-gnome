// Le décodage des signaux d'airdropd par l'extension : gjs -m tests/test_extension.js
import GLib from 'gi://GLib';

const here = GLib.path_get_dirname(GLib.filename_from_uri(import.meta.url)[0]);
const {describe, parseRequest, unpackSignal} = await import(`file://${here}/../extension/request.js`);

let failed = 0;
function check(name, got, want) {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    failed += ok ? 0 : 1;
    print(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok ? '' : ` : ${JSON.stringify(got)} ≠ ${JSON.stringify(want)}`}`);
}

// Exactement ce qu'émet airdropd (Request, signature ssaa{sv}as).
const file = (name, size) => ({name: new GLib.Variant('s', name), type: new GLib.Variant('s', 'public.png'),
    size: new GLib.Variant('t', size)});
const one = new GLib.Variant('(ssaa{sv}as)', ['r1', 'iPhone de Camille', [file('IMG_3346.PNG', 345017)], []]);
const req = parseRequest(unpackSignal(one));
check('nom du fichier, pas un Variant', req.files[0].name, 'IMG_3346.PNG');
check('taille en nombre', req.files[0].size, 345017);
check('texte de la notification', describe(req), `IMG_3346.PNG (${GLib.format_size(345017)})`);

const two = new GLib.Variant('(ssaa{sv}as)', ['r2', 'x', [file('a.png', 1000), file('b.png', 2000)], []]);
check('plusieurs fichiers', describe(parseRequest(unpackSignal(two))), `2 fichiers (${GLib.format_size(3000)})`);

const link = new GLib.Variant('(ssaa{sv}as)', ['r3', 'x', [], ['https://exemple.fr/page']]);
check('lien', describe(parseRequest(unpackSignal(link))), 'https://exemple.fr/page');

if (failed)
    imports.system.exit(1);
