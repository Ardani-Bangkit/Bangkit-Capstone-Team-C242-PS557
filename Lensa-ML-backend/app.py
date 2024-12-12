import os
import jwt
import tensorflow as tf
import numpy as np
from PIL import Image
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
import mysql.connector
import io
import uuid
from datetime import datetime
from dotenv import load_dotenv
import uvicorn
from uvicorn import Config, Server

load_dotenv()


app = FastAPI()


MODEL_SEVERITY_PATH = "model_frozen.tflite"  # Model untuk keparahan
MODEL_DISEASE_PATH = "model_jenis_penyakit_frozen.tflite"  # Model untuk penyakit kulit

# Load severity model
try:
    interpreter_severity = tf.lite.Interpreter(model_path=MODEL_SEVERITY_PATH)
    interpreter_severity.allocate_tensors()
    input_details_severity = interpreter_severity.get_input_details()
    output_details_severity = interpreter_severity.get_output_details()
except Exception as e:
    raise ValueError(f"Gagal memuat model keparahan: {str(e)}")

# Load disease identification model
try:
    interpreter_disease = tf.lite.Interpreter(model_path=MODEL_DISEASE_PATH)
    interpreter_disease.allocate_tensors()
    input_details_disease = interpreter_disease.get_input_details()
    output_details_disease = interpreter_disease.get_output_details()
except Exception as e:
    raise ValueError(f"Gagal memuat model penyakit: {str(e)}")

# Database connection
db_config = {
    "host": "34.34.218.3",
    "user": "root",
    "password": "lensa",
    "database": "auth_db"
}

def get_db_connection():
    try:
        connection = mysql.connector.connect(**db_config)
        return connection
    except mysql.connector.Error as err:
        raise Exception(f"Error connecting to database: {err}")


class VerifyToken(HTTPBearer):
    def __init__(self, auto_error: bool = True):
        super(VerifyToken, self).__init__(auto_error=auto_error)

    async def __call__(self, request: Request):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(status_code=401, detail="Authorization header missing")

        token = auth_header.split(" ")[1] if " " in auth_header else None
        if not token:
            raise HTTPException(status_code=401, detail="Token missing")

        try:
            # Decode token
            secret_key = os.getenv("ACCESS_TOKEN_SECRET")
            if not secret_key:
                raise HTTPException(status_code=500, detail="Server misconfigured: ACCESS_TOKEN_SECRET missing")

            decoded = jwt.decode(token, secret_key, algorithms=["HS256"])
            email = decoded.get("email")  # Asumsikan token mengandung email
            if not email:
                raise HTTPException(status_code=403, detail="email missing in token payload")

            # Query database to fetch id from users table
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            # Set id from database to request state
            request.state.id = user["id"]

        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=403, detail="Token has expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=403, detail="Invalid token")
        except mysql.connector.Error as err:
            raise HTTPException(status_code=500, detail=f"Database error: {err}")
        finally:
            cursor.close()
            connection.close()


# Use middleware in endpoints
security = VerifyToken()

# Save prediction result to database
def save_prediction_to_db(user_id: str, prediction_data: dict):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        query = """
            INSERT INTO predictions (user_id, nama_penyakit, description, severity, severityLevel, suggestion, createdAt)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (
            user_id,  # Masukkan user_id yang valid
            prediction_data["nama_penyakit"],
            prediction_data["description"],
            prediction_data["severity"],
            prediction_data["severityLevel"],
            ", ".join(prediction_data["suggestion"]),  # Pastikan suggestion adalah list yang bisa dijadikan string
            prediction_data["createdAt"]
        ))
        connection.commit()
    except mysql.connector.Error as err:
        connection.rollback()
        raise Exception(f"Failed to save prediction: {err}")
    finally:
        cursor.close()
        connection.close()

# Utility to preprocess image
def preprocess_image(image):
    tensor = tf.image.resize(image, (224, 224))
    tensor = tf.expand_dims(tensor, axis=0) 
    tensor = tf.cast(tensor, tf.float32) / 255.0  
    return tensor

# Prediction functions
def predict_severity(interpreter, image):
    tensor = preprocess_image(image)
    interpreter.set_tensor(input_details_severity[0]['index'], tensor.numpy())
    interpreter.invoke()
    predictions = interpreter.get_tensor(output_details_severity[0]['index'])[0]
    confidence_score = float(np.max(predictions)) * 100
    classes = ["Moderate", "Mild", "Severe"]
    severity_level = int(np.argmax(predictions))
    label = classes[severity_level]
    return {
        "confidenceScore": confidence_score,
        "severityLevel": severity_level,
        "label": label,
    }

def predict_disease(interpreter, image):
    tensor = preprocess_image(image)
    interpreter.set_tensor(input_details_disease[0]['index'], tensor.numpy())
    interpreter.invoke()
    predictions = interpreter.get_tensor(output_details_disease[0]['index'])[0]
    confidence_score = float(np.max(predictions)) * 100
    disease_classes = [
        "Acne and Rosacea", "Atopic Dermatitis", "Herpes",
        "Psoriasis", "Tinea Ringworm", "Wart"
    ]


    disease_descriptions = {
       "Acne and Rosacea": (
        "Acne is a skin condition that occurs due to clogged hair follicles from excess oil and dead skin cells. "
        "Rosacea is a chronic skin disease that causes redness on the face, particularly around the nose, cheeks, chin, and forehead. "
        "It is characterized by small bumps on the skin such as blackheads/whiteheads, pustules (filled with pus), papules (red without pus), or nodules (large painful bumps). "
        "These usually appear on the face, back, and chest, often caused by excess oil production, clogged pores, or hormonal changes."
        ),
       "Atopic Dermatitis": (
        "Atopic dermatitis, or atopic eczema, is a chronic skin condition that causes inflammation. "
        "The skin becomes very itchy, red, dry, and cracked. In severe cases, fluid may ooze from the skin. "
        "It commonly occurs in body folds such as elbows, knees, or neck. Often occurs in children but can persist into adulthood. "
        "This condition frequently recurs and is triggered by factors such as allergies, stress, cold weather, or excessively dry skin."
        ),
       "Herpes": (
        "Herpes is a skin infection caused by the herpes simplex virus (HSV). It appears as small, fluid-filled blisters that are painful or itchy. "
        "In oral herpes (HSV-1), blisters usually appear around the lips or mouth. In genital herpes (HSV-2), blisters occur in the genital area. "
        "Herpes often begins with symptoms such as a burning or tingling sensation in the infected area. "
        "It is contagious and transmitted through direct contact with sores, body fluids, or infected mucous membranes. "
        "The virus can remain dormant in the body and reactivate due to stress, weakened immunity, or sun exposure."
       ),
       "Psoriasis": (
        "Psoriasis is a chronic autoimmune disease that accelerates the regeneration of skin cells. "
        "This condition results in a buildup of skin cells on the surface, appearing as red patches with silvery scales. "
        "Psoriasis commonly occurs in areas such as the elbows, knees, lower back, or scalp. "
        "While not contagious, it can significantly affect the quality of life and is often triggered by stress, infections, or skin injuries."
       ),
       "Tinea Ringworm": (
        "Tinea ringworm is a fungal infection of the skin caused by dermatophytes. It manifests as a ring-shaped rash with raised, scaly edges "
        "and a lighter appearance in the center. This disease can affect various body parts, such as the body, scalp, feet, or nails. "
        "The infection is contagious and typically spreads through direct contact with infected skin or contaminated objects such as towels, clothing, or hygiene tools."
       ),
       "Wart": (
        "A wart is a small, rough skin growth caused by infection with the human papillomavirus (HPV). "
        "It appears as a small, rough, and hard bump on the skin's surface. Warts usually occur on the hands, feet, or fingers. "
        "Plantar warts (on the soles of the feet) can be painful when walking, while genital warts appear in the genital area. "
        "They may be flat, raised, or resemble a cauliflower in shape."
       ),
    }
 
    disease_label = disease_classes[int(np.argmax(predictions))]
    return {
        "confidenceScore": confidence_score,
        "label": disease_label,
        "description": disease_descriptions[disease_label],
        "suggestion": ["No specific suggestions available."],  # Placeholder
    }

suggestions_by_severity = {
     "Acne and Rosacea": [
        "Moderate: Use creams or serums with retinoids or azelaic acid to help reduce inflammation and prevent new lesions. Avoid direct sun exposure, and use sunscreen with at least SPF 30.",
        "Mild: Use a gentle, alcohol-free facial cleanser to prevent irritation. Avoid oily or spicy foods that may trigger acne and rosacea. Apply a lightweight moisturizer if your skin feels dry.",
        "Severe: Consult a dermatologist for oral medications like isotretinoin, effective for severe cases. Doctors may also recommend laser treatments or other therapies to reduce redness and inflammation."
     ],
     "Atopic Dermatitis": [
        "Moderate: Apply anti-inflammatory creams like corticosteroids as directed by a doctor to reduce itching and irritation. Avoid irritants like perfumes or rough fabrics.",
        "Mild: Use hypoallergenic moisturizers regularly, especially after bathing, to maintain skin hydration and prevent dryness. Avoid harsh soaps and use gentle cleansers.",
        "Severe: If the condition worsens, consult a doctor for systemic treatments like immunomodulators or biologic therapies to manage severe symptoms."
     ],
     "Herpes": [
        "Moderate: Take antiviral medications such as acyclovir or valacyclovir as prescribed by a doctor to speed up healing and reduce pain. Avoid triggers such as stress or fatigue.",
        "Mild: Keep the infected area clean and avoid touching the sores to prevent spreading. Use a clean cloth to dry the area and avoid sharing personal items.",
        "Severe: Seek immediate medical attention if herpes sores spread, become very painful, or are accompanied by symptoms like fever. Doctors may provide additional treatments to manage the infection."
     ],
     "Psoriasis": [
        "Moderate: Use corticosteroid ointments or UV therapy as recommended by a doctor to help reduce plaques and inflammation. Follow the treatment schedule regularly.",
        "Mild: Apply thick moisturizers to reduce dryness and plaque buildup. Avoid triggers like stress, smoking, or alcohol consumption that can worsen symptoms.",
        "Severe: For very severe cases, consult a doctor to consider biologic therapy or other systemic treatments. Doctors may also recommend intensive clinic-based care."
     ],
     "Tinea Ringworm": [
        "Moderate: If the infection does not improve or spreads, consult a doctor for oral antifungal medications. Avoid sharing items like towels or clothing to prevent transmission.",
        "Mild: Apply topical antifungal medications such as clotrimazole or miconazole regularly to the infected area. Keep the skin dry and clean to prevent the spread of infection.",
        "Severe: For very severe infections, see a dermatologist immediately. The doctor may prescribe stronger treatments or recommend additional tests to confirm the diagnosis."
     ],
     "Wart": [
        "Moderate: Consider cryotherapy (freezing the wart) at a clinic if the wart does not respond to topical treatments. This treatment is often effective for stubborn warts.",
        "Mild: Use over-the-counter treatments like salicylic acid ointments regularly to soften and remove small warts. Avoid cutting or scratching warts to prevent infection.",
        "Severe: If the wart is large, painful, or keeps spreading, consult a doctor for surgical removal, electrocautery, or laser treatment. The doctor may also recommend follow-up care."
     ]
}

def get_suggestions(disease: str, severity_level: int):
    """Get suggestions based on disease and severity level."""
    if disease in suggestions_by_severity:
        # Pastikan severity_level sesuai indeks yang ada
        if 0 <= severity_level < len(suggestions_by_severity[disease]):
            return [suggestions_by_severity[disease][severity_level]]
    return ["No specific suggestions available."]


@app.post("/predict")
async def post_predict_handler(
    request: Request,
    file: UploadFile = File(...),
    token: str = Depends(security)
):
    try:
        # Get user_id from request.state set by VerifyToken middleware
        user_id = request.state.id  # Gunakan request.state.id yang sudah di-set

        # Read image from file
        image_data = await file.read()
        image = Image.open(io.BytesIO(image_data))
        image = image.convert("RGB")

        # Convert image to numpy array
        image_array = tf.convert_to_tensor(np.array(image))

        # Perform predictions
        severity_result = predict_severity(interpreter_severity, image_array)
        disease_result = predict_disease(interpreter_disease, image_array)

        suggestions = get_suggestions(
            disease_result["label"],
            severity_result["severityLevel"]
        )
        # Combine results
        response_data = {
            "nama_penyakit": disease_result["label"],
            "description": disease_result["description"],
            "severity": severity_result["label"],
            "severityLevel": severity_result["severityLevel"],
            "suggestion": suggestions,
            "confidenceScore": {
                "severity": severity_result["confidenceScore"],
                "disease": disease_result["confidenceScore"],
            },
            "createdAt": datetime.utcnow().isoformat(),
        }


        # Save prediction to database
        save_prediction_to_db(user_id, response_data)  # Gunakan user_id yang didapatkan dari token

        return JSONResponse(
            content={
                "status": "success",
                "message": "Prediction completed successfully.",
                "data": response_data,
            },
            status_code=201,
        )
    except HTTPException as e:
        return JSONResponse(
            content={"status": "error", "message": e.detail},
            status_code=e.status_code,
        )
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "message": f"Prediction failed: {str(e)}"},
            status_code=500,
        )

@app.get("/predictions")
def get_predictions(request: Request, token: str = Depends(security)):
    try:
        # Ambil user_id dari request.state
        user_id = request.state.id

        # Koneksi ke database
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Ambil data prediksi berdasarkan user_id
        query = "SELECT * FROM predictions WHERE user_id = %s ORDER BY createdAt DESC"
        cursor.execute(query, (user_id,))
        predictions = cursor.fetchall()

        # Konversi hasil ke format JSON-friendly
        for prediction in predictions:
            if isinstance(prediction.get("createdAt"), datetime):
                prediction["createdAt"] = prediction["createdAt"].isoformat()  # Konversi ke string

        return JSONResponse(
            content={
                "status": "success",
                "message": "Predictions fetched successfully.",
                "data": predictions,
            },
            status_code=200,
        )
    except mysql.connector.Error as err:
        return JSONResponse(
            content={"status": "error", "message": f"Failed to fetch predictions: {err}"},
            status_code=500,
        )
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "message": f"Failed to fetch predictions: {str(e)}"},
            status_code=500,
        )
    finally:
        cursor.close()
        connection.close()



@app.get("/")
def home():
    return {"message": "API is running!"}


config = Config(app, host="0.0.0.0", port=8080)
server = Server(config)

if __name__ == "__main__":
    server.run()