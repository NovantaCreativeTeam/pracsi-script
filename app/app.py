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
    TRANSVERSAL_TIERS = ["Task", "Interactional segment", "Micro task", "Sequence", "Transaction", "Note"]

    # Funzione per trovare mosse dialogiche
    def find_moves(tier_name, begin, end, tiers):
        vals = []
        for tier in tiers:
            if tier["linguistic_type"] == tier_name:
                for ann in tier["annotations"]:
                    if (ann["begin"] == begin or ann["end"] == end or (ann["begin"] >= begin and ann["end"] == end)):
                        vals.append(ann["value"])
        return ", ".join(vals)

    # Funzione per valori tier trasversali
    def find_transversal_values(tier_name, begin, end, tiers):
        for tier in tiers:
            if tier["tier_id"] == tier_name:
                for ann in tier["annotations"]:
                    if ann["begin"] <= begin and ann["end"] >= end:
                        return ann["value"]
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
        for ann in tier.findall("ANNOTATION/ALIGNABLE_ANNOTATION"):
            t["annotations"].append({
                "begin": timeslots[ann.attrib["TIME_SLOT_REF1"]],
                "end": timeslots[ann.attrib["TIME_SLOT_REF2"]],
                "value": ann.findtext("ANNOTATION_VALUE", default="")
            })
        tiers.append(t)

    # Tier padre: linguistic_type="Parlante"
    rows = []
    for tier in tiers:
        if tier["linguistic_type"] == "Parlante":
            participant = tier["participant"]
            for ann in tier["annotations"]:
                row = {
                    "Begin": millis_to_timestamp(ann["begin"]),
                    "End": millis_to_timestamp(ann["end"]),
                    "Task": find_transversal_values("Task", ann["begin"], ann["end"], tiers),
                    "Interactional Segment": find_transversal_values("Interactional segment", ann["begin"], ann["end"], tiers),
                    "Micro Task": find_transversal_values("Micro task", ann["begin"], ann["end"], tiers),
                    "Sequence": find_transversal_values("Sequence", ann["begin"], ann["end"], tiers),
                    "Transaction": find_transversal_values("Transaction", ann["begin"], ann["end"], tiers),
                    "Participant": participant,
                    "Annotation": ann["value"],
                    "Non Verbal Action": find_moves("Non verbal action", ann["begin"], ann["end"], tiers),
                    "Move Level 1": find_moves("MoveLev1", ann["begin"], ann["end"], tiers),
                    "Move Level 2": find_moves("MoveLev2", ann["begin"], ann["end"], tiers),
                    "Move Level 3": find_moves("MoveLev3", ann["begin"], ann["end"], tiers),
                    "Note": find_transversal_values("Note", ann["begin"], ann["end"], tiers),
                }
                rows.append(row)

    # Ordina per Begin
    df = pd.DataFrame(rows)
    df.to_csv(csv_file, index=False)

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
    app.run(host="0.0.0.0", port=5000)
