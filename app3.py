from flask import Flask, render_template, request, redirect, url_for
import cv2
from pyzbar.pyzbar import decode
import firebase_admin
from firebase_admin import credentials, db
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# Firebase Initialization
firebase_cred = credentials.Certificate("service-account-key.json")  # Replace with your Firebase file
firebase_admin.initialize_app(firebase_cred, {
    'databaseURL': 'https://homecoming-f055b-default-rtdb.firebaseio.com/'  # Replace with your Firebase URL
})
ref = db.reference('event_data')

# Google Sheets Initialization
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
sheet_creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
client = gspread.authorize(sheet_creds)
sheet = client.open("Homecoming Data").sheet1  # Replace with your sheet name

# Helper: Fetch total plates by summing column C
def get_total_plates():
    plates_column = sheet.col_values(3)  # Column C is index 3
    total_plates = 0
    for plates in plates_column[1:]:
        try:
            total_plates += int(plates)
        except ValueError:
            continue
    return total_plates

# Helper: Fetch live served plate count from Google Sheets
def get_served_plate_count():
    all_records = sheet.get_all_records()
    served_count = sum(int(record.get('Remaining Plates', 0)) == 0 for record in all_records)
    return served_count

# Helper: Fetch and format live plate count
def get_plate_count():
    served_plates = get_served_plate_count()
    total_plates = get_total_plates()
    return f"Plates Served: {served_plates} / Total Plates: {total_plates}"

# Update Google Sheets
def update_google_sheet(data, qr_code, plates_given):
    all_records = sheet.get_all_records()
    matched_row = None

    for idx, record in enumerate(all_records, start=2):  # Start at row 2 to skip the header
        if record.get('QR Code') == qr_code:
            matched_row = idx
            break

    if matched_row:
        remaining_plates = int(sheet.cell(matched_row, 4).value)  # Assuming column 4 is "Remaining Plates"
        new_remaining = remaining_plates - plates_given
        sheet.update_cell(matched_row, 4, new_remaining)
        if new_remaining == 0:
            sheet.update_cell(matched_row, 5, 'Yes')  # Mark as served
    else:
        # Append new data with plates
        sheet.append_row([data.get('name', ''), data.get('phone', ''), data['plates'], data['plates'], 'No'])

    update_plate_count()

def update_plate_count():
    served_plates = get_served_plate_count()
    total_plates = get_total_plates()
    # Update live plate count in Column F (F1 cell)
    sheet.update_cell(1, 6, f"Plates Served: {served_plates} / Total Plates: {total_plates}")

# QR Code Scanning Function
def scan_qr():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: Could not open camera.")
        return None

    while True:
        _, frame = cap.read()
        for barcode in decode(frame):
            qr_data = barcode.data.decode("utf-8").strip()
            cap.release()
            cv2.destroyAllWindows()
            return qr_data

        cv2.imshow("QR Scanner", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    return None

# Routes for frontend pages
@app.route("/")
def home():
    plate_count = get_plate_count()
    return render_template("index.html", plate_count=plate_count)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.route("/services")
def services():
    return render_template("services.html")

@app.route("/scan_camera")
def scan_camera():
    qr_data = scan_qr()
    if qr_data:
        all_data = ref.get()
        match_key = None
        match = None

        for key, value in all_data.items():
            if value.get('qr_code') == qr_data:
                match = value
                match_key = key
                break

        if match:
            remaining_plates = match.get('remaining_plates', match['plates'])
            if remaining_plates > 0:
                return redirect(url_for("confirm_plates", qr_code=qr_data, remaining_plates=remaining_plates))
            else:
                return "No plates remaining for this QR code.", 400
        else:
            return "QR Code not found.", 404

    return redirect(url_for("home"))

@app.route("/confirm/<qr_code>/<remaining_plates>", methods=["GET", "POST"])
def confirm_plates(qr_code, remaining_plates):
    if request.method == "POST":
        plates_given = int(request.form["plates_given"])
        remaining_plates = int(remaining_plates)

        if plates_given > remaining_plates:
            return f"Error: Cannot give more than {remaining_plates} plates.", 400

        all_data = ref.get()
        match_key = None
        match = None

        for key, value in all_data.items():
            if value.get('qr_code') == qr_code:
                match = value
                match_key = key
                break

        if match:
            new_remaining = remaining_plates - plates_given
            ref.child(match_key).update({"remaining_plates": new_remaining})
            update_google_sheet(match, qr_code, plates_given)
            return redirect(url_for("plates_page", plates_to_give=plates_given))

    return render_template("confirm.html", qr_code=qr_code, remaining_plates=remaining_plates)

@app.route("/plates/<plates_to_give>")
def plates_page(plates_to_give):
    return render_template("plates.html", plates_to_give=plates_to_give)

@app.route("/done")
def done():
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True)
