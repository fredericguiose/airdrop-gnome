// Ce que l'extension tire des signaux d'airdropd, sans rien de GNOME Shell :
// testable avec gjs seul (tests/test_extension.js).

import GLib from 'gi://GLib';

// Les paramètres d'un signal, en valeurs JS jusqu'au bout : deepUnpack
// laisserait les a{sv} en GLib.Variant (« [object variant] » à l'écran).
export function unpackSignal(params) {
    return params.recursiveUnpack();
}

// Request(id, expéditeur, fichiers aa{sv}, liens) → ce qu'affiche la notification.
export function parseRequest([id, sender, files, urls]) {
    return {
        id,
        sender,
        files: files.map(f => ({name: String(f.name), size: Number(f.size ?? 0)})),
        urls,
    };
}

export function describe({files, urls}) {
    if (urls.length)
        return urls.join('\n');
    const total = files.reduce((n, f) => n + f.size, 0);
    const size = GLib.format_size(total);
    if (files.length === 1)
        return `${files[0].name} (${size})`;
    return `${files.length} fichiers (${size})`;
}
