from flask import Flask, request, send_file, render_template
import pandas as pd
import xml.etree.ElementTree as ET
import os

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ---------------------------------------------
# FUNZIONI DI CONVERSIONE EAF → CSV
# ---------------------------------------------
def millis_to_timestamp(ms):
    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    milliseconds = ms % 1000
    return f"{minutes:02}:{seconds:02}.{milliseconds:03}"

def parse_eaf_to_csv(eaf_file, csv_file):
    tree = ET.parse(eaf_file)
    root = tree.getroot()

    # Dizionario timeslot
    timeslots = {ts.attrib["TIME_SLOT_ID"]: int(ts.attrib["TIME_VALUE"]) for ts in root.find("TIME_ORDER")}

    # Tier trasversali
    TRANSVERSAL_TIERS = ["Task", "Interactional segment", "Micro task", "Sequence", "Transaction"]

    # Funzione per trovare mosse dialogiche
    def find_moves(tier_name, begin, end, participant, tiers):
        vals = []
        for tier in tiers:
            if tier["linguistic_type"] == tier_name and tier["participant"] == participant:
                for ann in tier["annotations"]:
                    if (ann["begin"] == begin or ann["end"] == end or (ann["begin"] >= begin and ann["end"] <= end) or (ann["begin"] <= begin and ann["end"] >= end)):
                        vals.append(ann["value"])
        return ", ".join(vals)

    # Funzione per valori tier trasversali
    def find_transversal_values(tier_name, begin, end, tiers):
        for tier in tiers:
            if tier["tier_id"] == tier_name:
                for idx, ann in enumerate(tier["annotations"], start=1):
                    if not (ann["end"] < begin or ann["begin"] > end):
                        # Se c'è un valore, restituiscilo; altrimenti restituisci l'indice
                        return ann["value"] if ann["value"].strip() else str(idx)
        return ""


    # Lettura tiers
    tiers = []
    for tier in root.findall("TIER"):
        t = {
            "tier_id": tier.attrib.get("TIER_ID", ""),
            "participant": tier.attrib.get("PARTICIPANT", ""),
            "linguistic_type": tier.attrib.get("LINGUISTIC_TYPE_REF", ""),
            "annotations": []
        }
        for ann in tier.findall("ANNOTATION/ALIGNABLE_ANNOTATION") + tier.findall("ANNOTATION/REF_ANNOTATION"):
            # begin e end: se è REF_ANNOTATION allora ha ANNOTATION_REF invece dei TIME_SLOT_REF1/2
            if ann.tag.endswith("ALIGNABLE_ANNOTATION"):
                begin = timeslots[ann.attrib["TIME_SLOT_REF1"]]
                end = timeslots[ann.attrib["TIME_SLOT_REF2"]]
            else:  # REF_ANNOTATION
                # in REF_ANNOTATION non ci sono TIME_SLOT, quindi eventualmente recuperi i valori dalla annotazione referenziata
                ref_id = ann.attrib["ANNOTATION_REF"]
                ref_ann = next(
                    (a for t in tiers for a in t["annotations"] if a.get("id") == ref_id),
                    None
                )
                if ref_ann:
                    begin = ref_ann["begin"]
                    end = ref_ann["end"]
                else:
                    continue  # salta se non trovi la referenza

            t["annotations"].append({
                "id": ann.attrib.get("ANNOTATION_ID", ""),
                "begin": begin,
                "end": end,
                "value": ann.findtext("ANNOTATION_VALUE", default="")
            })
        tiers.append(t)

    # Crea lista di tutte le annotazioni dei Parlante per calcolare le pause
    all_parlante_anns = []
    for tier in tiers:
        if tier["linguistic_type"] == "Parlante":
            for ann in tier["annotations"]:
                if ann["begin"] is not None and ann["end"] is not None:
                    all_parlante_anns.append(ann)

    # Ordina per inizio
    all_parlante_anns.sort(key=lambda x: x["begin"])

    # Genera pause dai gap tra annotazioni
    pause_rows = []
    prev_end = 0
    for ann in all_parlante_anns:
        if ann["begin"] > prev_end:
            pause_duration_sec = (ann["begin"] - prev_end) / 1000

            # creiamo una pausa
            pause_row = {
                "_begin_ms": prev_end,
                "_end_ms": ann["begin"],
                "Begin": millis_to_timestamp(prev_end),
                "End": millis_to_timestamp(ann["begin"]),
                "Task": find_transversal_values("Task", prev_end, ann["begin"], tiers),
                "Interactional Segment": find_transversal_values("Interactional segment", prev_end, ann["begin"], tiers),
                "Micro Task": find_transversal_values("Micro task", prev_end, ann["begin"], tiers),
                "Sequence": find_transversal_values("Sequence", prev_end, ann["begin"], tiers),
                "Transaction": find_transversal_values("Transaction", prev_end, ann["begin"], tiers),
                "Participant": "",
                "Annotation": f"({pause_duration_sec:.2f})",
                "Non Verbal Action": "",
                "Move Level 1": "",
                "Move Level 2": "",
                "Move Level 3": ""
            }
            pause_rows.append(pause_row)
        prev_end = max(prev_end, ann["end"])

    # Aggiungi le annotazioni normali dei Parlante
    rows = pause_rows.copy()
    for tier in tiers:
        if tier["linguistic_type"] == "Parlante":
            participant = tier["participant"]
            for ann in tier["annotations"]:
                if ann["begin"] is None or ann["end"] is None:
                    continue
                row = {
                    "_begin_ms": ann["begin"],
                    "_end_ms": ann["end"],
                    "Begin": millis_to_timestamp(ann["begin"]),
                    "End": millis_to_timestamp(ann["end"]),
                    "Task": find_transversal_values("Task", ann["begin"], ann["end"], tiers),
                    "Interactional Segment": find_transversal_values("Interactional segment", ann["begin"], ann["end"], tiers),
                    "Micro Task": find_transversal_values("Micro task", ann["begin"], ann["end"], tiers),
                    "Sequence": find_transversal_values("Sequence", ann["begin"], ann["end"], tiers),
                    "Transaction": find_transversal_values("Transaction", ann["begin"], ann["end"], tiers),
                    "Participant": participant,
                    "Annotation": ann["value"],
                    "Non Verbal Action": find_moves("Non verbal action", ann["begin"], ann["end"], participant, tiers),
                    "Move Level 1": find_moves("MoveLev1", ann["begin"], ann["end"], participant, tiers),
                    "Move Level 2": find_moves("MoveLev2", ann["begin"], ann["end"], participant, tiers),
                    "Move Level 3": find_moves("MoveLev3", ann["begin"], ann["end"], participant, tiers)
                }
                rows.append(row)

    for tier in tiers:
        if tier["tier_id"] == "Note":
            for ann in tier["annotations"]:
                rows.append({
                    "_begin_ms": ann["begin"],
                    "_end_ms": ann["end"],
                    "Begin": millis_to_timestamp(ann["begin"]),
                    "End": millis_to_timestamp(ann["end"]),
                    "Task": find_transversal_values("Task", ann["begin"], ann["end"], tiers),
                    "Interactional Segment": find_transversal_values("Interactional segment", ann["begin"], ann["end"], tiers),
                    "Micro Task": find_transversal_values("Micro task", ann["begin"], ann["end"], tiers),
                    "Sequence": find_transversal_values("Sequence", ann["begin"], ann["end"], tiers),
                    "Transaction": find_transversal_values("Transaction", ann["begin"], ann["end"], tiers),
                    "Participant": "Note",
                    "Annotation": ann["value"],
                    "Non Verbal Action": "",
                    "Move Level 1": "",
                    "Move Level 2": "",
                    "Move Level 3": ""
                })

    rows.sort(key=lambda x: x["_begin_ms"])

    # Crea DataFrame e ordina colonne
    df = pd.DataFrame(rows)
    df.insert(df.columns.get_loc("Participant"), "Row", df.index + 1)
    df = df.drop(columns=["_begin_ms", "_end_ms"])  # cancella colonne tecniche

    df.to_csv(csv_file, index=True)

# ---------------------------------------------
# ROUTE FLASK
# ---------------------------------------------
@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return "Nessun file caricato", 400

    file = request.files["file"]
    if file.filename == "":
        return "Nessun file selezionato", 400

    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(file_path)

    csv_file = os.path.splitext(file_path)[0] + ".csv"
    parse_eaf_to_csv(file_path, csv_file)  # converte EAF → CSV

    return send_file(csv_file, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
