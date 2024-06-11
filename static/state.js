export let state = {
    mnemonicPhrase: '',
    userAddress: '',
    currentLanguage: 'en',
    activeDialog: '',
    theme: 'light'
};

export function saveState() {
    localStorage.setItem('appState', JSON.stringify(state));
}

export function loadState() {
    const storedState = localStorage.getItem('appState');
    if (storedState) {
        const parsedState = JSON.parse(storedState);
        state = { ...state, ...parsedState };
    }
}

export function clearState() {
    state = {
        mnemonicPhrase: '',
        userAddress: '',
        currentLanguage: 'en',
        activeDialog: '',
        theme: 'light'
    };
    saveState();
}
