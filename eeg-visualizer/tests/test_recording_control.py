"""
Test di can_start_recording(): il cancello che decide quando il pulsante
Start puo' essere premuto.

Impostano lo stato direttamente sull'istanza invece di passare per gli
handler dei segnali Qt (update_impedance_visuals, update_predictions_visuals):
can_start_recording legge solo tre attributi, non serve simulare l'intero
percorso degli eventi per isolarne la logica.
"""


def test_bloccato_se_impedenza_troppo_alta(visualizer):
    visualizer.impedance_data = visualizer.IMPEDANCE_THRESHOLD + 1
    visualizer.last_fft_zscores = {'Alpha': 0.5}
    visualizer.recording_active = False
    assert visualizer.can_start_recording() is False


def test_bloccato_senza_il_primo_zscore(visualizer):
    visualizer.impedance_data = 1000
    visualizer.last_fft_zscores = None
    visualizer.recording_active = False
    assert visualizer.can_start_recording() is False


def test_bloccato_se_gia_in_registrazione(visualizer):
    """
    Anche con impedenza e z-score a posto, Start deve restare bloccato se
    una registrazione e' gia' in corso: altrimenti un doppio click aprirebbe
    due CSV per la stessa sessione.
    """
    visualizer.impedance_data = 1000
    visualizer.last_fft_zscores = {'Alpha': 0.5}
    visualizer.recording_active = True
    assert visualizer.can_start_recording() is False


def test_sbloccato_con_tutte_le_condizioni_soddisfatte(visualizer):
    visualizer.impedance_data = 1000
    visualizer.last_fft_zscores = {'Alpha': 0.5}
    visualizer.recording_active = False
    assert visualizer.can_start_recording() is True


def test_soglia_impedenza_e_inclusiva(visualizer):
    """
    Il confronto e' <=, non <: un'impedenza esattamente alla soglia deve
    sbloccare Start, non bloccarlo.
    """
    visualizer.impedance_data = visualizer.IMPEDANCE_THRESHOLD
    visualizer.last_fft_zscores = {'Alpha': 0.5}
    visualizer.recording_active = False
    assert visualizer.can_start_recording() is True


def test_appena_oltre_la_soglia_resta_bloccato(visualizer):
    visualizer.impedance_data = visualizer.IMPEDANCE_THRESHOLD + 1
    visualizer.last_fft_zscores = {'Alpha': 0.5}
    visualizer.recording_active = False
    assert visualizer.can_start_recording() is False


def test_stato_iniziale_prima_di_qualunque_dato_reale(raw_visualizer):
    """
    Un'istanza appena creata, prima che arrivi il primo pacchetto di
    impedenza o il primo z-score dall'SDK, deve avere Start bloccato.
    impedance_data parte da sys.maxsize (valore sentinella "device non
    ancora connesso"), non da un valore realistico: se questo default
    cambiasse per errore, Start potrebbe risultare sbloccato prima ancora
    che il dispositivo sia connesso.
    """
    assert raw_visualizer.last_fft_zscores is None
    assert raw_visualizer.can_start_recording() is False