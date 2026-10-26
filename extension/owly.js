// Une session de réception AirDrop : `owly radio up` tient la radio (owlyd la
// rend si ce processus meurt), `owly receive` répond à l'iPhone. On lit ce que
// le CLI écrit et on répond à sa question « accept? [y/N] » sur son stdin.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const OWLY = 'owly';
const PROMPT = 'accept? [y/N] ';
const SIGINT = 2;

// Owly écrit les noms avec le {:?} de Rust : guillemets, \" \\ \n \t \r,
// \u{1f600}. On le relit comme du JSON une fois les \u{...} réécrits.
export function unquote(s) {
    s = s.trim();
    if (!s.startsWith('"') || !s.endsWith('"'))
        return s;
    const json = s.replace(/\\u\{([0-9a-fA-F]+)\}/g, (_, hex) =>
        String.fromCodePoint(parseInt(hex, 16)));
    try {
        return JSON.parse(json);
    } catch {
        return s.slice(1, -1);
    }
}

// Lit un flux par morceaux et rend des lignes ; `onPartial` voit le reste non
// terminé (la question d'Owly n'a pas de retour à la ligne).
// Le TextDecoder de GJS n'a pas l'option `stream` : on garde les octets et on
// ne décode que des lignes entières, pour ne jamais couper un caractère UTF-8.
export function readStream(stream, cancellable, onLine, onPartial) {
    const decoder = new TextDecoder();
    let buffer = new Uint8Array(0);
    const next = () => {
        stream.read_bytes_async(4096, GLib.PRIORITY_DEFAULT, cancellable, (s, res) => {
            let bytes;
            try {
                bytes = s.read_bytes_finish(res);
            } catch {
                return;
            }
            if (bytes.get_size() === 0)
                return;
            const chunk = bytes.toArray();
            const joined = new Uint8Array(buffer.length + chunk.length);
            joined.set(buffer);
            joined.set(chunk, buffer.length);
            buffer = joined;
            let i;
            while ((i = buffer.indexOf(10)) >= 0) {
                try {
                    onLine(decoder.decode(buffer.subarray(0, i)));
                } catch (e) {
                    console.error(`AirDrop: ${e}`);
                }
                buffer = buffer.slice(i + 1);
            }
            if (buffer.length && onPartial?.(decoder.decode(buffer)))
                buffer = new Uint8Array(0);
            next();
        });
    };
    next();
}

// Événements émis vers l'interface :
//   state(name)          'starting' | 'receiving' | 'stopped'
//   request({sender, files: [{name, size}], urls: [], answer(bool)})
//   expired()            la demande n'a pas eu de réponse à temps
//   withdrawn()          l'iPhone a annulé
//   received(path)       un fichier est arrivé
//   url(url)             un lien accepté est arrivé
//   failed(reason)
export class ReceiveSession {
    constructor({dir, seconds}, handlers) {
        this._dir = dir;
        this._seconds = seconds;
        this._on = handlers;
        this._cancellable = new Gio.Cancellable();
        this._stopped = false;
    }

    start() {
        this._emit('state', 'starting');
        try {
            this._radio = Gio.Subprocess.new(
                [OWLY, 'radio', 'up', '--for', String(this._seconds)],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE);
        } catch (e) {
            this._fail(`owly introuvable : ${e.message}`);
            return;
        }
        let up = false;
        readStream(this._radio.get_stdout_pipe(), this._cancellable, line => {
            if (!up && line.startsWith('awdl0 is up')) {
                up = true;
                this._startReceiver();
            } else if (line.startsWith('owly: ') || line.startsWith('error')) {
                this._lastRadioError = line;
            }
        });
        // `--for` rend la radio tout seul : la session s'arrête avec elle.
        this._radio.wait_async(null, () => {
            if (!up && !this._stopped)
                this._fail(this._lastRadioError ?? 'la radio AirDrop n\'a pas démarré');
            else
                this.stop();
        });
    }

    _startReceiver() {
        if (this._stopped)
            return;
        this._receiver = Gio.Subprocess.new(
            [OWLY, 'receive', '--dir', this._dir],
            Gio.SubprocessFlags.STDIN_PIPE |
            Gio.SubprocessFlags.STDOUT_PIPE |
            Gio.SubprocessFlags.STDERR_PIPE);
        this._receiver.wait_async(null, () => this.stop());

        // stdout : les chemins reçus, ou les liens entre guillemets.
        readStream(this._receiver.get_stdout_pipe(), this._cancellable, line => {
            if (line.startsWith('"'))
                this._emit('url', unquote(line));
            else if (line.startsWith('/'))
                this._emit('received', line);
        });

        // stderr : les demandes et la question.
        let request = null;
        readStream(this._receiver.get_stderr_pipe(), this._cancellable, line => {
            const ask = line.match(/^(".*") \((".*")\) wants to send:$/);
            if (ask) {
                request = {sender: unquote(ask[1]), files: [], urls: []};
            } else if (request && line.startsWith('  ')) {
                const file = line.match(/^ {2}(".*") (\S+) (?:(\d+) bytes)?$/);
                if (file)
                    request.files.push({name: unquote(file[1]), type: file[2], size: file[3] ? Number(file[3]) : null});
                else
                    request.urls.push(unquote(line));
            } else if (line.startsWith('receiving as')) {
                this._emit('state', 'receiving');
            } else if (line.trim() === 'timed out') {
                this._emit('expired');
            } else if (line.startsWith('the request was withdrawn')) {
                this._emit('withdrawn');
            } else if (line.startsWith('transfer failed: ')) {
                this._emit('failed', line.slice('transfer failed: '.length));
            }
        }, partial => {
            if (!partial.endsWith(PROMPT) || !request)
                return false;
            const r = request;
            request = null;
            let answered = false;
            r.answer = yes => {
                if (answered || this._stopped)
                    return;
                answered = true;
                this._write(yes ? 'y\n' : 'n\n');
            };
            this._emit('request', r);
            return true;
        });
    }

    _write(text) {
        try {
            this._receiver?.get_stdin_pipe()?.write_all(new TextEncoder().encode(text), null);
        } catch (e) {
            console.warn(`AirDrop: ${e.message}`);
        }
    }

    _fail(reason) {
        this._emit('failed', reason);
        this.stop();
    }

    // Ctrl-C pour les deux : owly rend la radio proprement, et owlyd la
    // reprend de toute façon si le processus disparaît.
    stop() {
        if (this._stopped)
            return;
        this._stopped = true;
        this._receiver?.send_signal(SIGINT);
        this._radio?.send_signal(SIGINT);
        this._cancellable.cancel();
        this._emit('state', 'stopped');
    }

    _emit(name, ...args) {
        try {
            this._on[name]?.(...args);
        } catch (e) {
            console.error(`AirDrop: ${name}: ${e}`);
        }
    }
}
