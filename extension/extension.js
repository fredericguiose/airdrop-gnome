// Le bouton AirDrop : une télécommande d'airdropd (D-Bus, session). Aucun
// processus ici ; c'est le service qui parle à Owly et tient la radio.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as MessageTray from 'resource:///org/gnome/shell/ui/messageTray.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {QuickMenuToggle, SystemIndicator} from 'resource:///org/gnome/shell/ui/quickSettings.js';

const ICON = 'network-wireless-hotspot-symbolic';
const DURATIONS = [2, 5, 10];
const DEFAULT_MINUTES = 5;

const BUS_NAME = 'fr.portalstudio.AirDrop';
const PATH = '/fr/portalstudio/AirDrop';
const IFACE = 'fr.portalstudio.AirDrop1';

function describe(files, urls) {
    if (urls.length)
        return urls.join('\n');
    const total = files.reduce((n, f) => n + f.size, 0);
    const size = GLib.format_size(total);
    if (files.length === 1)
        return `${files[0].name} (${size})`;
    return `${files.length} fichiers (${size})`;
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
        this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
            'Le Wi-Fi est coupé pendant la réception,\npuis rétabli après le transfert.',
            {reactive: false}));
        this.menu.addAction('Envoyer des fichiers…', () => indicator.pickFiles());
        this.menu.addAction('Ouvrir Téléchargements', () => indicator.openDownloads());

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
        this._icon = this._addIndicator();
        this._icon.icon_name = ICON;
        this._icon.visible = false;

        this._toggle = new AirDropToggle(this);
        this.quickSettingsItems.push(this._toggle);

        this._requests = new Map();  // id → notification
        this._cancellable = new Gio.Cancellable();
        // Pas d'auto-démarrage pour suivre l'état : airdropd ne démarre
        // qu'au premier vrai appel (D-Bus l'active alors).
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START, null,
            BUS_NAME, PATH, IFACE, this._cancellable, (_o, res) => {
                try {
                    this._proxy = Gio.DBusProxy.new_for_bus_finish(res);
                } catch (e) {
                    if (!e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                        console.error(`AirDrop: ${e.message}`);
                    return;
                }
                this._proxy.connect('g-signal', (_p, _sender, name, params) =>
                    this._onSignal(name, params.deepUnpack()));
                this._proxy.connect('g-properties-changed', () => this._sync());
                this._proxy.connect('notify::g-name-owner', () => this._sync());
                this._sync();
            });
    }

    _prop(name, fallback) {
        return this._proxy?.get_cached_property(name)?.unpack() ?? fallback;
    }

    _call(method, args = null) {
        // Sans DO_NOT_AUTO_START sur l'appel : c'est lui qui lance airdropd.
        Gio.DBus.session.call(BUS_NAME, PATH, IFACE, method, args, null,
            Gio.DBusCallFlags.NONE, -1, null, (conn, res) => {
                try {
                    conn.call_finish(res);
                } catch (e) {
                    this._starting = false;
                    this._notify('AirDrop indisponible', Gio.DBusError.strip_remote_error(e) || e.message);
                    this._sync();
                }
            });
    }

    toggle(minutes) {
        if (this._prop('ReceivingUntil', 0) > 0 || this._starting) {
            this._starting = false;
            this._call('StopReceiving');
        } else {
            this._starting = true;
            this._call('StartReceiving', new GLib.Variant('(u)', [minutes * 60]));
        }
        this._sync();
    }

    pickFiles() {
        Main.panel.statusArea.quickSettings.menu.close();
        this._spawn(['airdrop-send']);
    }

    openDownloads() {
        const dir = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) ?? GLib.get_home_dir();
        Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(dir, null), null);
    }

    _spawn(argv) {
        try {
            Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);
        } catch (e) {
            this._notify('AirDrop', `${argv[0]} introuvable : ${e.message}`);
        }
    }

    _sync() {
        const until = this._prop('ReceivingUntil', 0);
        const radio = this._prop('Radio', 'idle');
        const on = until > 0;
        if (on)
            this._starting = false;
        const t = this._toggle;
        t.checked = on || this._starting;
        this._icon.visible = t.checked;

        if (on && radio === 'up') {
            this._tick();
            this._timer ||= GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => this._tick());
        } else {
            this._clearTimer();
            t.subtitle = t.checked ? 'Démarrage…' : 'Désactivé';
        }
    }

    _tick() {
        const until = this._prop('ReceivingUntil', 0);
        const left = Math.max(0, Math.round((until - GLib.get_real_time()) / 1e6));
        const mm = Math.floor(left / 60), ss = String(left % 60).padStart(2, '0');
        this._toggle.subtitle = `Visible · ${mm}:${ss}`;
        return GLib.SOURCE_CONTINUE;
    }

    _clearTimer() {
        if (this._timer)
            GLib.source_remove(this._timer);
        this._timer = 0;
    }

    _onSignal(name, args) {
        switch (name) {
        case 'Request': {
            const [id, sender, files, urls] = args;
            this._onRequest(id, sender, files.map(f => ({name: f.name, size: Number(f.size)})), urls);
            break;
        }
        case 'RequestClosed': {
            const [id, reason] = args;
            this._dismiss(id);
            if (reason === 'expired')
                this._notify('Demande expirée', 'Personne n\'a répondu à temps.');
            else if (reason === 'withdrawn')
                this._notify('Envoi annulé', 'L\'appareil a annulé l\'envoi.');
            break;
        }
        case 'Received':
            this._onReceived(args[0]);
            break;
        case 'UrlReceived':
            this._onUrl(args[0]);
            break;
        case 'ReceiveFailed':
            this._notify('Échec de la réception', args[0]);
            break;
        case 'RadioFailed':
            // Peut venir d'un autre client (la fenêtre d'envoi) : ne parler
            // que si c'est la réception qui démarrait.
            if (this._starting || this._prop('ReceivingUntil', 0) > 0)
                this._notify('Impossible de démarrer AirDrop', args[0]);
            this._starting = false;
            this._sync();
            break;
        }
    }

    _onRequest(id, sender, files, urls) {
        const n = this._notify(`${sender} veut vous envoyer`, describe(files, urls), {
            urgency: MessageTray.Urgency.CRITICAL,
            resident: true,
        });
        let answered = false;
        const answer = yes => {
            if (answered)
                return;
            answered = true;
            this._requests.delete(id);
            // Déjà réglée côté service, ou extension en train de s'arrêter :
            // ne rien renvoyer (et ne pas relancer airdropd pour rien).
            if (!n._airdropClosed && !this._destroying)
                this._call('Answer', new GLib.Variant('(sb)', [id, yes]));
            n.destroy();
        };
        n.addAction('Refuser', () => answer(false));
        n.addAction('Accepter', () => answer(true));
        // Fermer la notification, c'est refuser.
        n.connect('destroy', () => answer(false));
        this._requests.set(id, n);
    }

    _dismiss(id) {
        const n = this._requests.get(id);
        this._requests.delete(id);
        if (n) {
            // Déjà réglée côté service : ne pas répondre une seconde fois.
            n._airdropClosed = true;
            n.destroy();
        }
    }

    _onReceived(path) {
        const file = Gio.File.new_for_path(path);
        const n = this._notify('Fichier reçu', file.get_basename());
        n.addAction('Afficher', () => this._showInFolder(file));
        n.addAction('Ouvrir', () => Gio.AppInfo.launch_default_for_uri(file.get_uri(), null));
    }

    _onUrl(url) {
        // On n'ouvre que du web, comme Owly le recommande (SEC-4).
        if (/^https?:\/\//i.test(url))
            Gio.AppInfo.launch_default_for_uri(url, null);
        this._notify('Lien reçu', url);
    }

    _showInFolder(file) {
        Gio.DBus.session.call(
            'org.freedesktop.FileManager1', '/org/freedesktop/FileManager1',
            'org.freedesktop.FileManager1', 'ShowItems',
            new GLib.Variant('(ass)', [[file.get_uri()], '']),
            null, Gio.DBusCallFlags.NONE, -1, null, null);
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
        this._destroying = true;
        this._cancellable.cancel();
        this._clearTimer();
        for (const n of this._requests.values())
            n.destroy();
        this._requests.clear();
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
