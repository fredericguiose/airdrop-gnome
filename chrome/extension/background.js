// Envoie une adresse au relais local (native messaging), qui ouvre la fenêtre
// d'envoi d'airdrop-gnome : c'est elle qui trouve les appareils et envoie.
// L'extension n'a accès ni au Wi-Fi ni au Bluetooth, et n'en a pas besoin.

const HOST = 'fr.portalstudio.airdrop';

chrome.runtime.onInstalled.addListener(() => {
    chrome.contextMenus.create({
        id: 'airdrop-page',
        title: 'Envoyer la page via AirDrop',
        contexts: ['page'],
    });
    chrome.contextMenus.create({
        id: 'airdrop-link',
        title: 'Envoyer le lien via AirDrop',
        contexts: ['link'],
    });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
    send(info.menuItemId === 'airdrop-link' ? info.linkUrl : (info.pageUrl ?? tab?.url), tab);
});

chrome.action.onClicked.addListener(tab => send(tab.url, tab));

async function send(url, tab) {
    // Un iPhone n'ouvrira que du web ; chrome://, file:// n'ont pas de sens là-bas.
    if (!/^https?:\/\//i.test(url ?? '')) {
        await flag(tab, 'Seules les pages web (http, https) peuvent être envoyées.');
        return;
    }
    try {
        const reply = await chrome.runtime.sendNativeMessage(HOST, {url});
        if (!reply?.ok)
            throw new Error(reply?.error ?? 'réponse inattendue du relais');
        await flag(tab, null);
    } catch (e) {
        // Le plus souvent : relais non installé (chrome/install.sh).
        await flag(tab, `AirDrop : ${e.message}`);
    }
}

// Un « ! » sur le bouton et l'erreur en infobulle ; effacé au prochain succès.
async function flag(tab, error) {
    const tabId = tab?.id;
    await chrome.action.setBadgeText({tabId, text: error ? '!' : ''});
    await chrome.action.setBadgeBackgroundColor({tabId, color: '#d93025'});
    await chrome.action.setTitle({tabId, title: error ?? 'Envoyer cette page via AirDrop'});
    if (error)
        console.warn(error);
}
