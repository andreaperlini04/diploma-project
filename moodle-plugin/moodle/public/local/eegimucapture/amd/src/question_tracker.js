// This file is part of Moodle - http://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// Moodle is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with Moodle.  If not, see <http://www.gnu.org/licenses/>.

/**
 * Rilevazione dell'attività dell'utente sulla pagina.
 *
 * Estrae i dati dal DOM di Moodle, classifica semanticamente le interazioni
 * con le domande e registra i listener sulle cinque sorgenti. Produce messaggi
 * interni {event_type, payload, ts_browser_ms} per la callback di initAll();
 * non conosce l'envelope del backend né il trasporto.
 *
 * @module     local_eegimucapture/question_tracker
 * @copyright  2026 Andrea Perlini <andreap0446@gmail.com>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
define([], function() {

    // Estrazione dati dal DOM.

    /**
     * Normalizza una stringa collassando gli spazi consecutivi, applicando
     * il trim e troncando alla lunghezza indicata.
     *
     * @param {string|null} text Testo da normalizzare.
     * @param {number} [max] Lunghezza massima del risultato.
     * @return {string|null} Testo normalizzato, o null se vuoto o assente.
     */
    function clean(text, max) {
        if (!text) {
            return null;
        }
        var t = text.replace(/\s+/g, ' ').trim();
        if (!t) {
            return null;
        }
        return max ? t.slice(0, max) : t;
    }

    /**
     * Etichetta visibile di un elemento interattivo.
     *
     * Si opera su un clone privato dei nodi per screen reader, per non
     * alterare la pagina. Ripiego su aria-label.
     *
     * @param {HTMLElement} el Elemento da etichettare.
     * @return {string|null} Etichetta normalizzata, o null.
     */
    function visibleLabel(el) {
        if (!el) {
            return null;
        }
        if (el.tagName === 'INPUT') {
            var t = (el.type || '').toLowerCase();
            if (t === 'submit' || t === 'button') {
                return clean(el.value, 80);
            }
        }
        var clone = el.cloneNode(true);
        var hidden = clone.querySelectorAll('.accesshide, .sr-only, .visually-hidden, [aria-hidden="true"]');
        for (var i = 0; i < hidden.length; i++) {
            if (hidden[i].parentNode) {
                hidden[i].parentNode.removeChild(hidden[i]);
            }
        }
        var text = clean(clone.textContent, 80);
        if (!text) {
            var aria = el.getAttribute('aria-label');
            text = aria ? clean(aria, 80) : null;
        }
        return text;
    }

    /**
     * Risale al contenitore .que della domanda.
     *
     * @param {HTMLElement} el Elemento di partenza.
     * @return {HTMLElement|null} Contenitore .que, o null.
     */
    function questionContainer(el) {
        return (el && el.closest) ? el.closest('.que') : null;
    }

    /**
     * Ricava il qtype dalla lista di classi del contenitore .que.
     *
     * @param {HTMLElement|null} que Contenitore .que.
     * @return {string|null} Nome del qtype, o null.
     */
    function questionType(que) {
        if (!que) {
            return null;
        }
        var m = que.className.match(/\bque\s+([a-z0-9_]+)/i);
        return m ? m[1] : null;
    }

    /**
     * Testo dell'enunciato della domanda.
     *
     * @param {HTMLElement|null} que Contenitore .que.
     * @return {string|null} Testo dell'enunciato, o null.
     */
    function questionText(que) {
        if (!que) {
            return null;
        }
        var qt = que.querySelector('.qtext');
        return qt ? clean(qt.innerText, 150) : null;
    }

    /**
     * Numero d'ordine della domanda, letto dall'attributo data-number con
     * fallback sul contenuto di .no .qno.
     *
     * @param {HTMLElement|null} que Contenitore .que.
     * @return {number|null} Numero della domanda, o null.
     */
    function questionNumber(que) {
        if (!que) {
            return null;
        }
        var dn = que.getAttribute('data-number');
        if (dn) {
            return parseInt(dn, 10) || null;
        }
        var qno = que.querySelector('.no .qno');
        if (qno) {
            return parseInt(qno.innerText, 10) || null;
        }
        return null;
    }

    /**
     * Testo della label associata a un input radio o checkbox.
     *
     * Ordine di risoluzione: aria-labelledby, label contenitore, contenitore
     * .r0 o .r1.
     *
     * @param {HTMLElement} input Input radio o checkbox.
     * @return {string|null} Testo della risposta, o null.
     */
    function choiceLabel(input) {
        var labelEl = null;
        var labelledBy = input.getAttribute('aria-labelledby');
        if (labelledBy) {
            labelEl = document.getElementById(labelledBy);
        }
        if (!labelEl) {
            labelEl = input.closest('label');
        }
        if (!labelEl) {
            labelEl = input.closest('.r0, .r1');
        }
        return labelEl ? clean(labelEl.innerText, 120) : null;
    }

    /**
     * Testo dell'opzione selezionata in un elemento select.
     *
     * @param {HTMLElement} el Elemento da leggere. Il tipo è verificato nel
     *     corpo: un elemento diverso da select produce null.
     * @return {string|null} Testo dell'opzione, o null.
     */
    function selectAnswer(el) {
        if (el.tagName !== 'SELECT') {
            return null;
        }
        var opt = el.options[el.selectedIndex];
        return opt ? clean(opt.text, 120) : null;
    }

    /**
     * Testo della sotto-domanda associata a una select di tipo match,
     * letto dalla cella td.text della riga corrispondente.
     *
     * @param {HTMLElement} el Elemento select.
     * @return {string|null} Testo della sotto-domanda, o null.
     */
    function matchSubQuestion(el) {
        var row = el.closest('tr');
        if (!row) {
            return null;
        }
        var cell = row.querySelector('td.text');
        return cell ? clean(cell.innerText, 120) : null;
    }

    /**
     * Numero di place ricavato dalla classe placeN dell'elemento.
     *
     * Applicabile sia allo slot di destinazione (.placeN.drop) sia
     * all'input di stato (.placeinput.placeN).
     *
     * @param {HTMLElement} el Elemento con classe placeN.
     * @return {number|null} Numero di place, o null.
     */
    function placeNumber(el) {
        var m = el.className.match(/\bplace(\d+)\b/);
        return m ? parseInt(m[1], 10) : null;
    }

    /**
     * Numero di gruppo da una classe groupN presente sull'elemento.
     *
     * In ddwtos la numerazione delle choice riparte da 1 in ogni gruppo: il
     * solo numero di choice non identifica un elemento.
     *
     * @param {HTMLElement} el L'elemento con classe groupN.
     * @return {number|null} Numero di gruppo, o null.
     */
    function groupNumber(el) {
        var m = el.className.match(/\bgroup(\d+)\b/);
        return m ? parseInt(m[1], 10) : null;
    }

    /**
     * Testo accessibile dello slot di destinazione ddwtos, per target_text.
     *
     * Il suffisso "Question N" è ridondante con question_number e va rimosso.
     *
     * @param {HTMLElement} que Contenitore .que.
     * @param {number|null} placeNum Numero di place.
     * @return {string|null} Testo dello slot, o null.
     */
    function dropAccessibleText(que, placeNum) {
        if (!que || placeNum === null) {
            return null;
        }
        var drop = que.querySelector('.place' + placeNum + '.drop');
        if (!drop) {
            return null;
        }
        var hidden = drop.querySelector('.accesshide');
        if (!hidden) {
            return null;
        }
        var text = clean(hidden.textContent, 120);
        return text ? text.replace(/\s+Question\s+\d+\s*$/i, '') : null;
    }

    /**
     * Testo dell'elemento trascinabile corrispondente al numero di choice
     * indicato, usato come item_text.
     *
     * La ricerca è circoscritta al gruppo: la numerazione riparte da 1 in
     * ciascuno, quindi `.draghome.choiceN` da solo trova la prima in ordine di
     * documento, del gruppo sbagliato in tutti i casi tranne uno.
     *
     * @param {HTMLElement} que Contenitore .que.
     * @param {number|null} choiceNum Numero di choice, relativo al gruppo.
     * @param {number|null} groupNum Numero di gruppo.
     * @return {string|null} Testo dell'elemento, o null.
     */
    function dragChoiceText(que, choiceNum, groupNum) {
        if (!que || choiceNum === null || isNaN(choiceNum)) {
            return null;
        }
        var selector = '.draghome.choice' + choiceNum;
        if (groupNum !== null && !isNaN(groupNum)) {
            selector += '.group' + groupNum;
        }
        var drag = que.querySelector(selector);
        return drag ? clean(drag.textContent, 80) : null;
    }

    // Ultima risposta per chiave, viva quanto la pagina. Distingue
    // answer_selected (prima scelta) da answer_changed (scelta successiva).
    var lastAnswer = {};

    // Classificazione semantica delle risposte.

    /**
     * Campi comuni ai payload relativi a una domanda.
     *
     * @param {HTMLElement|null} que Contenitore .que.
     * @return {Object} Oggetto con question_number e question_text.
     */
    function baseFields(que) {
        return {
            question_number: questionNumber(que),
            question_text:   questionText(que)
        };
    }

    /**
     * Chiave identificativa della domanda: numero d'ordine, con fallback
     * sul testo dell'enunciato.
     *
     * @param {HTMLElement|null} que Contenitore .que.
     * @return {string} Chiave della domanda.
     */
    function questionKey(que) {
        var qnum = questionNumber(que);
        return qnum !== null ? String(qnum) : (questionText(que) || '?');
    }

    /**
     * Modello a valore singolo sostituibile: multichoice a scelta unica,
     * truefalse, match.
     *
     * @param {string} key Chiave della risposta.
     * @param {string|null} value Valore corrente.
     * @param {Object} base Campi comuni del payload.
     * @return {Object|null} Oggetto {event_type, payload}, o null se il
     *     valore è invariato.
     */
    function applyReplacement(key, value, base) {
        var prev = lastAnswer[key];
        lastAnswer[key] = value;

        var payload = {};
        var k;
        for (k in base) {
            if (base.hasOwnProperty(k)) {
                payload[k] = base[k];
            }
        }

        if (prev === undefined || prev === null) {
            payload.answer_text = value;
            return {event_type: 'answer_selected', payload: payload};
        }
        if (prev === value) {
            return null;
        }
        if (value === null) {
            payload.answer_text = prev;
            return {event_type: 'answer_cleared', payload: payload};
        }
        payload.old_answer_text = prev;
        payload.new_answer_text = value;
        return {event_type: 'answer_changed', payload: payload};
    }

    /**
     * Modello a caselle indipendenti, usato dalle checkbox.
     *
     * @param {boolean} checked Stato della checkbox.
     * @param {string|null} value Testo della risposta.
     * @param {Object} base Campi comuni del payload.
     * @return {Object} Oggetto {event_type, payload}.
     */
    function applyToggle(checked, value, base) {
        var payload = {};
        for (var k in base) {
            if (base.hasOwnProperty(k)) {
                payload[k] = base[k];
            }
        }
        payload.answer_text = value;
        return {
            event_type: checked ? 'answer_selected' : 'answer_cleared',
            payload: payload
        };
    }

    /**
     * Modello a testo libero: ogni modifica produce un text_answer_entered.
     *
     * @param {string|null} value Testo inserito.
     * @param {Object} base Campi comuni del payload.
     * @return {Object} Oggetto {event_type, payload}.
     */
    function applyText(value, base) {
        var payload = {};
        for (var k in base) {
            if (base.hasOwnProperty(k)) {
                payload[k] = base[k];
            }
        }
        payload.answer_text = value;
        return {event_type: 'text_answer_entered', payload: payload};
    }

    // Associazione tra qtype e modello semantico applicabile.
    var qtypeHandlers = {

        // Le radio seguono il modello a sostituzione, le checkbox quello a
        // caselle indipendenti.
        multichoice: function(el, que) {
            if ((el.type || '').toLowerCase() === 'checkbox') {
                return applyToggle(el.checked, choiceLabel(el), baseFields(que));
            }
            return applyReplacement('q:' + questionKey(que), choiceLabel(el), baseFields(que));
        },

        truefalse: function(el, que) {
            return applyReplacement('q:' + questionKey(que), choiceLabel(el), baseFields(que));
        },

        // La chiave combina domanda e sotto-domanda: ogni riga della tabella
        // mantiene uno stato indipendente.
        match: function(el, que) {
            var subq = matchSubQuestion(el);
            var base = baseFields(que);
            base.sub_question = subq;
            var key = 'q:' + questionKey(que) + '|s:' + (subq || '');
            return applyReplacement(key, selectAnswer(el), base);
        },

        shortanswer: function(el, que) {
            return applyText(clean(el.value, 200), baseFields(que));
        },

        numerical: function(el, que) {
            return applyText(clean(el.value, 200), baseFields(que));
        },

        essay: function(el, que) {
            return applyText(clean(el.value, 200), baseFields(que));
        }
    };

    /**
     * Instrada l'elemento verso il modello semantico del proprio qtype.
     *
     * @param {HTMLElement} el Elemento che porta la risposta: input radio o
     *     checkbox dalla sorgente click, oppure select, input di testo o
     *     numerico e textarea dalla sorgente change.
     * @param {HTMLElement} que Contenitore .que.
     * @return {Object|null} Oggetto {event_type, payload}, o null se il qtype
     *     non ha un modello associato o se il modello non produce eventi per
     *     questa transizione.
     */
    function buildChoiceEvent(el, que) {
        var handler = qtypeHandlers[questionType(que)];
        return handler ? handler(el, que) : null;
    }

    /**
     * Costruisce il messaggio per gli eventi di navigazione, non associati
     * a una domanda con qtype riconosciuto.
     *
     * @param {HTMLElement} el Elemento sorgente.
     * @param {string} eventType Valore 'click' oppure 'input_change'.
     * @return {Object} Messaggio in formato interno.
     */
    function buildPayload(el, eventType) {
        var que = questionContainer(el);
        return {
            event_type:      eventType,
            qtype:           questionType(que),
            question_number: questionNumber(que),
            question_text:   questionText(que),
            target_tag:      el.tagName || null,
            target_text:     visibleLabel(el),
            target_id:       el.id || null,
            target_type:     el.type || null,
            ts_browser_ms:   Date.now()
        };
    }

    /**
     * Costruisce il messaggio per gli eventi già classificati da un modello.
     *
     * @param {string} eventType Tipo semantico dell'evento.
     * @param {Object} payload Payload strutturato.
     * @return {Object} Messaggio in formato interno.
     */
    function buildPassthrough(eventType, payload) {
        return {
            event_type:    eventType,
            payload:       payload,
            ts_browser_ms: Date.now()
        };
    }

    // Sorgenti di eventi.

    /**
     * Sorgente 1: click su link, pulsanti, radio e checkbox.
     *
     * Radio e checkbox qui e non su change: click precede change e consente la
     * delega con closest(). Select, testo e textarea restano su change.
     *
     * @param {Function} send Callback di invio del messaggio.
     * @return {void}
     */
    function initClickTracking(send) {
        document.addEventListener('click', function(e) {
            var target = e.target.closest(
                'a, button, input[type="submit"], input[type="radio"], input[type="checkbox"]'
            );
            if (!target) {
                return;
            }

            // I controlli Video.js sono button e produrrebbero un evento di
            // navigazione oltre a video_started/video_paused. Si esclude il
            // contenitore e non .vjs-control: il pulsante di avvio sovrapposto
            // non porta quella classe.
            if (target.closest('.video-js')) {
                return;
            }

            var que = questionContainer(target);
            var qtype = questionType(que);

            if (qtype && qtypeHandlers[qtype] &&
                target.tagName === 'INPUT' &&
                (target.type === 'radio' || target.type === 'checkbox')) {
                var result = buildChoiceEvent(target, que);
                if (result) {
                    send(buildPassthrough(result.event_type, result.payload));
                }
                return;
            }

            send(buildPayload(target, 'click'));
        });
    }

    /**
     * Sorgente 2: change su campi di testo, campi numerici, select e
     * textarea.
     *
     * @param {Function} send Callback di invio del messaggio.
     * @return {void}
     */
    function initChangeTracking(send) {
        document.addEventListener('change', function(e) {
            var target = e.target;
            if (!target) {
                return;
            }

            var tag = target.tagName;
            var type = (target.type || '').toLowerCase();

            var isText = (tag === 'INPUT' && (type === 'text' || type === 'number'));
            var isSelect = (tag === 'SELECT');
            var isTextarea = (tag === 'TEXTAREA');

            if (!isText && !isSelect && !isTextarea) {
                return;
            }

            var que = questionContainer(target);
            var qtype = questionType(que);

            if (qtype && qtypeHandlers[qtype]) {
                var result = buildChoiceEvent(target, que);
                if (result) {
                    send(buildPassthrough(result.event_type, result.payload));
                }
                return;
            }

            send(buildPayload(target, 'input_change'));
        });
    }

    /**
     * Sorgente 3: question_displayed per le domande presenti al
     * caricamento di attempt.php, una sola volta per domanda.
     *
     * @param {Function} send Callback di invio del messaggio.
     * @return {void}
     */
    function initQuestionDisplayTracking(send) {
        var displayed = {};

        /**
         * Emette question_displayed per un contenitore .que.
         *
         * @param {HTMLElement} que Contenitore .que.
         * @param {number} indexOffsetMs Scostamento in millisecondi
         *     determinato dalla posizione della domanda nella pagina.
         * @return {void}
         */
        function emitQuestionDisplayed(que, indexOffsetMs) {
            if (!window.location.href.match(/\/mod\/quiz\/attempt\.php/)) {
                return;
            }
            var qnum = questionNumber(que);
            var key = qnum !== null ? String(qnum) : (questionText(que) || '?');
            if (displayed[key]) {
                return;
            }
            displayed[key] = true;

            send({
                event_type: 'question_displayed',
                payload: {
                    question_number: qnum,
                    question_text:   questionText(que),
                    // Le domande descrittive non hanno numero: il qtype
                    // permette al backend di descriverle comunque.
                    qtype:           questionType(que)
                },
                // Il vincolo di unicità del backend non comprende il payload e
                // le domande di una pagina cadrebbero sullo stesso millisecondo,
                // perdendone tutte tranne una. Lo scostamento per posizione
                // preserva l'ordine con errore pari al numero di domande.
                ts_browser_ms: Date.now() + indexOffsetMs
            });
        }

        var queEls = document.querySelectorAll('.que');
        for (var i = 0; i < queEls.length; i++) {
            emitQuestionDisplayed(queEls[i], i);
        }
    }

    /**
     * Sorgente 4: drag and drop into text (ddwtos).
     *
     * Il componente di Moodle non emette change sugli input nascosti di stato:
     * si confrontano i valori su mouseup.
     *
     * @param {Function} send Callback di invio del messaggio.
     * @return {void}
     */
    function initDragDropTracking(send) {
        var ddwtosState = {};

        /**
         * Acquisisce lo stato iniziale degli input .placeinput presenti
         * nella pagina.
         *
         * @return {void}
         */
        function initDdwtosState() {
            var inputs = document.querySelectorAll('.que.ddwtos input.placeinput');
            for (var i = 0; i < inputs.length; i++) {
                ddwtosState[inputs[i].name] = inputs[i].value;
            }
        }
        initDdwtosState();

        document.addEventListener('mouseup', function() {
            var inputs = document.querySelectorAll('.que.ddwtos input.placeinput');
            for (var i = 0; i < inputs.length; i++) {
                var inp = inputs[i];
                var prev = ddwtosState[inp.name];
                var curr = inp.value;

                if (curr === prev) {
                    continue;
                }
                ddwtosState[inp.name] = curr;

                var que = questionContainer(inp);
                var placeNum = placeNumber(inp);
                // Il gruppo si legge dall'input di stato, che porta placeN e
                // groupN: è il solo modo di identificare l'elemento collocato.
                var groupNum = groupNumber(inp);
                var payload = baseFields(que);
                payload.target_text = dropAccessibleText(que, placeNum);

                if (curr === '0') {
                    // Convenzione ddwtos: '0' se lo slot è vuoto, altrimenti il
                    // numero della choice collocata, a base 1.
                    payload.item_text = dragChoiceText(que, parseInt(prev, 10), groupNum);
                    // Per answer_cleared il backend legge answer_text.
                    payload.answer_text = payload.item_text;
                    send(buildPassthrough('answer_cleared', payload));
                } else {
                    payload.item_text = dragChoiceText(que, parseInt(curr, 10), groupNum);
                    send(buildPassthrough('drag_drop_completed', payload));
                }
            }
        });
    }

    /**
     * Sorgente 5: play e pause sugli elementi video.
     *
     * Copre i soli video presenti al caricamento della pagina.
     *
     * @param {Function} send Callback di invio del messaggio.
     * @return {void}
     */
    function initVideoTracking(send) {

        /**
         * Costruisce il payload di un evento video.
         *
         * Su Moodle title è di norma vuoto, da cui i ripieghi su aria-label e
         * sul nome del file della sorgente.
         *
         * @param {HTMLVideoElement} video Elemento video.
         * @return {Object} Oggetto con video_name e video_id.
         */
        function videoBaseFields(video) {
            return {
                video_name: clean(video.title, 120) ||
                            clean(video.getAttribute('aria-label'), 120) ||
                            clean((video.currentSrc || '').split('/').pop(), 120),
                video_id:   video.id || null
            };
        }

        var videoEls = document.querySelectorAll('video');
        for (var vi = 0; vi < videoEls.length; vi++) {
            (function(video) {
                video.addEventListener('play', function() {
                    send(buildPassthrough('video_started', videoBaseFields(video)));
                });
                video.addEventListener('pause', function() {
                    send(buildPassthrough('video_paused', videoBaseFields(video)));
                });
            })(videoEls[vi]);
        }
    }

    return {
        /**
         * Registra i listener di tutte le sorgenti di eventi.
         *
         * @param {Function} send Callback che riceve i messaggi prodotti.
         * @return {void}
         */
        initAll: function(send) {
            initClickTracking(send);
            initChangeTracking(send);
            initQuestionDisplayTracking(send);
            initDragDropTracking(send);
            initVideoTracking(send);
        }
    };
});
