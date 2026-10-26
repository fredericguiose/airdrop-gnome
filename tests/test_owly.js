// La lecture de la sortie d'owly par l'extension : gjs -m tests/test_owly.js
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const here = GLib.path_get_dirname(GLib.filename_from_uri(import.meta.url)[0]);
const {unquote, readStream} = await import(`file://${here}/../extension/owly.js`);

let failed = 0;
function check(name, got, want) {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    if (!ok)
        failed++;
    print(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok ? '' : `: ${JSON.stringify(got)} ≠ ${JSON.stringify(want)}`}`);
}

check('unquote', unquote('"iPhone de Frédéric"'), 'iPhone de Frédéric');
check('unquote \\u{}', unquote('"emoji \\u{1f600} \\"cité\\".txt"'), 'emoji 😀 "cité".txt');

// Un é coupé entre deux écritures, et la question sans retour à la ligne.
const loop = new GLib.MainLoop(null, false);
const script = `printf '"iPhone de Fr\\303'; sleep 0.2; printf '\\251d\\303\\251ric" ("iPhone") wants to send:\\naccept? [y/N] '; sleep 0.3; printf 'fin\\n'`;
const p = Gio.Subprocess.new(['sh', '-c', script], Gio.SubprocessFlags.STDOUT_PIPE);
const lines = [], prompts = [];
readStream(p.get_stdout_pipe(), null, l => lines.push(l), part => {
    if (!part.endsWith('accept? [y/N] '))
        return false;
    prompts.push(part);
    return true;
});
p.wait_async(null, () => GLib.timeout_add(0, 200, () => loop.quit()));
loop.run();
check('lignes', lines, ['"iPhone de Frédéric" ("iPhone") wants to send:', 'fin']);
check('question', prompts, ['accept? [y/N] ']);

if (failed)
    imports.system.exit(1);
