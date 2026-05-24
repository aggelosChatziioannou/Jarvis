# Jarvis Audio Cues — Πότε παίζει ο κάθε ήχος

Όλοι οι ήχοι είναι **procedural** (φτιάχνονται με κώδικα/numpy) — δεν χρειάζονται εξωτερικά αρχεία, internet, ούτε άδειες.

---

## 🔊 Οι 8 ήχοι + Χρήση

### 1. `wake_ack.wav` — "Σ' άκουσα!"
- **Πότε:** Αμέσως μετά που το Jarvis καταλάβει το wake word ("Jarvis") και ο intent judge αποφασίσει ότι είναι έγκυρο.
- **Πριν από:** Το thinking tune.
- **Σκοπός:** Ο χρήστης ξέρει αμέσως ότι το σύστημα ξύπνησε — δεν περιμένει σιωπή.

```
User: "Jarvis, what's the weather?"
       ↓
   [wake_ack.wav]  ← "Μπλιπ!" (150ms)
       ↓
   [thinking tune starts]
```

---

### 2. `searching.wav` — "Ψάχνω..."
- **Πότε:** Πριν από κάθε "αργή" ενέργεια: `webSearch`, MCP calls, `fetch_web_page`, screenshot analysis.
- **Σκοπός:** Γεμίζει τη σιωπή των 3-8 δευτερολέπτων που παίρνει ένα tool. Ο χρήστης ξέρει "κάτι γίνεται".

```
[thinking tune]
       ↓
Planner: χρειάζεται webSearch
       ↓
   [searching.wav]  ← "Μπιπ-μπιπ-μπιπ" (300ms)
       ↓
[web search runs... 3-5 sec]
       ↓
   [tool_success.wav]
```

---

### 3. `tool_success.wav` — "Έγινε!"
- **Πότε:** Όταν ένα tool επιστρέφει επιτυχώς (δεν έχει error, δεν timed out).
- **Σκοπός:** Ακουστική επιβεβαίωση ότι το tool ολοκληρώθηκε. Χαρούμενος, σύντομος.

---

### 4. `tool_fail.wav` — "Δεν πέτυχε"
- **Πότε:** Όταν ένα tool αποτυγχάνει (network error, invalid args, timeout, empty result).
- **Σκοπός:** Ενημερώνει τον χρήστη ότι κάτι πήγε στραβά — το Jarvis θα προσπαθήσει αλλιώς ή θα ζητήσει διευκρίνιση.

---

### 5. `hot_window_open.wav` — "Είμαι εδώ..."
- **Πότε:** Όταν τελειώσει το TTS και ανοίγει το hot window (παράθυρο συνέχειας).
- **Σκοπός:** Πολύ διακριτικό cue ότι το Jarvis περιμένει follow-up χωρίς wake word.

```
Jarvis: "The weather is sunny, 22 degrees."
       ↓
   [hot_window_open.wav]  ← Πολύ απαλό (350ms)
       ↓
User: "And tomorrow?"   ← Δεν χρειάζεται "Jarvis"!
```

---

### 6. `listening.wav` — "Προχώρα"
- **Πότε:** Όταν ο χρήστης μιλάει μέσα στο hot window (follow-up detected).
- **Σκοπός:** Επιβεβαιώνει ότι το follow-up καταγράφηκε. Πιο ήπιο από το `wake_ack`.

---

### 7. `stop_ack.wav` — "Σταμάτησα"
- **Πότε:** Όταν ο χρήστης λέει "stop" / "quiet" / "shush" και το TTS διακόπτεται.
- **Σκοπός:** Επιβεβαιώνει ότι η εντολή stop έγινε δεκτή — ο χρήστης δεν αναρωτιέται "το άκουσε;"

```
Jarvis: "The weather today is..."
User: "Stop!"
       ↓
   [stop_ack.wav]  ← Γρήγορο "ντουπ" (100ms)
       ↓
[TTS stops, thinking tune stops]
```

---

### 8. `wake_reject.wav` — "Όχι για μένα"
- **Πότε:** Όταν το wake word ανιχνεύεται αλλά ο intent judge απορρίπτει (false positive, ambient noise).
- **Σκοπός:** (Προαιρετικό) Αν το wake word ενεργοποιείται από λάθος, ο ήχος λέει "το άκουσα αλλά αγνοήθηκε".

---

## 🎬 Πλήρης ροή παραδείγματος

```
User:  "Jarvis, search for news from Greece"
          ↓
    [wake_ack.wav]           ← "Μπλιπ!" (150ms)
          ↓
    [thinking tune]          ← Αρχίζει το pad
          ↓
    Planner → webSearch
          ↓
    [searching.wav]          ← "Μπιπ-μπιπ-μπιπ" (300ms)
          ↓
    [web search... 4 sec]    ← Σιωπή με thinking tune
          ↓
    [tool_success.wav]       ← "Τιν-τιν-τιν!" (200ms)
          ↓
    LLM generates response
          ↓
    [thinking tune stops]
    [TTS speaks...]
          ↓
    "Here are the latest news from Greece..."
          ↓
    [hot_window_open.wav]    ← Απαλό swell (350ms)
          ↓
    👂 Hot window active (6 sec)
          ↓
User:  "And from France?"
          ↓
    [listening.wav]          ← Κουδούνι (250ms)
          ↓
    [repeat flow...]
```

---

## 🛠️ Πώς να αλλάξεις έναν ήχο

1. Άνοιξε το `generate_cues.py`
2. Βρες τη συνάρτηση που θες (π.χ. `make_searching`)
3. Άλλαξε συχνότητες, διάρκεια, ή τύπο ήχου
4. Τρέξε: `python generate_cues.py`
5. Άκουσε το νέο `.wav`

---

## 📦 Μέγεθος

Σύνολο: ~170 KB για όλους τους ήχους. Τα μισά είναι procedural (0 bytes στο bundle), τα υπόλοιπα είναι tiny.
