import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as MessageTray from 'resource:///org/gnome/shell/ui/messageTray.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {QuickMenuToggle, SystemIndicator} from 'resource:///org/gnome/shell/ui/quickSettings.js';

import {ReceiveSession} from './owly.js';

const ICON = 'network-wireless-hotspot-symbolic';
const DURATIONS = [2, 5, 10];
const DEFAULT_MINUTES = 5;
// Owly refuse tout seul au bout de 15 s (ASK-2) : on prévient un peu avant.
const ANSWER_SECONDS = 14;
// Après un transfert, on rend le Wi-Fi : le temps qu'un éventuel second
// fichier du même envoi arrive.
const LINGER_SECONDS = 3;

function formatSize(bytes) {
    return bytes == null ? '' : GLib.format_size(bytes);
}

function describe(request) {
    if (request.urls.length)
        return request.urls.join('\n');
    const total = request.files.reduce((n, f) => n + (f.size ?? 0), 0);
    if (request.files.length === 1)
        return `${request.files[0].name} (${formatSize(total)})`;
    return `${request.files.length} fichiers (${formatSize(total)})`;
}

const AirDropToggle = GObject.registerClass(
class AirDropToggle extends QuickMenuToggle {
    _init(indicator) {
        super._init({
            title: 'AirDrop',
            subtitle: 'Désactivé',
            iconName: ICON,
            toggleMode: false,
        });
        this._indicator = indicator;
        this._minutes = DEFAULT_MINUTES;

        this.menu.setHeader(ICON, 'AirDrop', 'Recevoir depuis un iPhone ou un Mac');

        this._durationItems = new Map();
        for (const m of DURATIONS) {
            const item = new PopupMenu.PopupMenuItem(`Visible pendant ${m} min`);
            item.connect('activate', () => {
                this._minutes = m;
                this._syncDurations();
            });
            this._durationItems.set(m, item);
            this.menu.addMenuItem(item);
        }
        this._syncDurations();

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const note = new PopupMenu.PopupMenuItem(
            'Le Wi-Fi est coupé pendant la réception,\npuis rétabli après le transfert.',
            {reactive: false});
        this.menu.addMenuItem(note);
        this.menu.addAction('Ouvrir Téléchargements', () =>
            Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(indicator.downloadDir, null), null));

        this.connect('clicked', () => indicator.toggle(this._minutes));
    }

    _syncDurations() {
        for (const [m, item] of this._durationItems)
            item.setOrnament(m === this._minutes ? PopupMenu.Ornament.CHECK : PopupMenu.Ornament.NONE);
    }
});

const AirDropIndicator = GObject.registerClass(
class AirDropIndicator extends SystemIndicator {
    _init() {
        super._init();
        this.downloadDir = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) ??
            GLib.get_home_dir();

        this._icon = this._addIndicator();
        this._icon.icon_name = ICON;
        this._icon.visible = false;

        this._toggle = new AirDropToggle(this);
        this.quickSettingsItems.push(this._toggle);
    }

    toggle(minutes) {
        if (this._session)
            this._session.stop();
        else
            this._start(minutes);
    }

    _start(minutes) {
        this._deadline = GLib.get_monotonic_time() + minutes * 60 * 1e6;
        this._session = new ReceiveSession({dir: this.downloadDir, seconds: minutes * 60}, {
            state: s => this._onState(s),
            request: r => this._onRequest(r),
            expired: () => this._closeRequest('Demande expirée', 'Personne n\'a répondu à temps.'),
            withdrawn: () => this._closeRequest('Envoi annulé', 'L\'appareil a annulé l\'envoi.'),
            received: path => this._onReceived(path),
            url: url => this._onUrl(url),
            failed: reason => this._notify('Échec AirDrop', reason),
        });
        this._session.start();
    }

    _onState(state) {
        const t = this._toggle;
        if (state === 'starting') {
            t.checked = true;
            t.subtitle = 'Démarrage…';
            this._icon.visible = true;
        } else if (state === 'receiving') {
            this._tick();
            this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => this._tick());
        } else if (state === 'stopped') {
            this._session = null;
            this._clearTimers();
            this._dismissRequest();
            t.checked = false;
            t.subtitle = 'Désactivé';
            this._icon.visible = false;
        }
    }

    _tick() {
        const left = Math.max(0, Math.round((this._deadline - GLib.get_monotonic_time()) / 1e6));
        const mm = Math.floor(left / 60), ss = String(left % 60).padStart(2, '0');
        this._toggle.subtitle = `Visible · ${mm}:${ss}`;
        return GLib.SOURCE_CONTINUE;
    }

    _onRequest(request) {
        this._dismissRequest();
        const n = this._notify(`${request.sender} veut vous envoyer`, describe(request), {
            urgency: MessageTray.Urgency.CRITICAL,
            resident: true,
        });
        let answered = false;
        const answer = yes => {
            if (answered)
                return;
            answered = true;
            request.answer(yes);
            this._dismissRequest();
            if (yes)
                this._toggle.subtitle = 'Réception…';
        };
        n.addAction('Refuser', () => answer(false));
        n.addAction('Accepter', () => answer(true));
        n.connect('destroy', () => answer(false));
        this._request = n;
        this._answerTimer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, ANSWER_SECONDS, () => {
            this._answerTimer = 0;
            answer(false);
            return GLib.SOURCE_REMOVE;
        });
    }

    _closeRequest(title, body) {
        this._dismissRequest();
        this._notify(title, body);
    }

    _dismissRequest() {
        if (this._answerTimer) {
            GLib.source_remove(this._answerTimer);
            this._answerTimer = 0;
        }
        const n = this._request;
        this._request = null;
        n?.destroy();
    }

    _onReceived(path) {
        const file = Gio.File.new_for_path(path);
        const n = this._notify('Fichier reçu', file.get_basename());
        n.addAction('Afficher', () => this._showInFolder(file));
        n.addAction('Ouvrir', () => Gio.AppInfo.launch_default_for_uri(file.get_uri(), null));
        this._lingerThenStop();
    }

    _onUrl(url) {
        // On n'ouvre que du web, comme Owly le recommande (SEC-4).
        if (/^https?:\/\//i.test(url))
            Gio.AppInfo.launch_default_for_uri(url, null);
        this._notify('Lien reçu', url);
        this._lingerThenStop();
    }

    _showInFolder(file) {
        Gio.DBus.session.call(
            'org.freedesktop.FileManager1', '/org/freedesktop/FileManager1',
            'org.freedesktop.FileManager1', 'ShowItems',
            new GLib.Variant('(ass)', [[file.get_uri()], '']),
            null, Gio.DBusCallFlags.NONE, -1, null, null);
    }

    _lingerThenStop() {
        if (this._lingerTimer)
            GLib.source_remove(this._lingerTimer);
        this._lingerTimer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, LINGER_SECONDS, () => {
            this._lingerTimer = 0;
            this._session?.stop();
            return GLib.SOURCE_REMOVE;
        });
    }

    _clearTimers() {
        for (const id of ['_timer', '_lingerTimer']) {
            if (this[id])
                GLib.source_remove(this[id]);
            this[id] = 0;
        }
    }

    _notify(title, body, params = {}) {
        if (!this._source) {
            this._source = new MessageTray.Source({title: 'AirDrop', iconName: ICON});
            this._source.connect('destroy', () => {
                this._source = null;
            });
            Main.messageTray.add(this._source);
        }
        const n = new MessageTray.Notification({source: this._source, title, body, ...params});
        this._source.addNotification(n);
        return n;
    }

    destroy() {
        this._session?.stop();
        this._clearTimers();
        this._dismissRequest();
        this._source?.destroy();
        this.quickSettingsItems.forEach(i => i.destroy());
        super.destroy();
    }
});

export default class AirDropExtension extends Extension {
    enable() {
        this._indicator = new AirDropIndicator();
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
