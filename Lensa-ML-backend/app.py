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
    classes = ["sedang", "ringan", "Parah"]
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
            "Acne adalah kondisi kulit yang terjadi akibat penyumbatan folikel rambut oleh minyak berlebih dan sel kulit mati. "
            "Rosacea adalah penyakit kulit kronis yang menyebabkan kemerahan pada wajah, terutama di sekitar hidung, pipi, dagu, dan dahi. "
            "Ditandai dengan benjolan kecil pada kulit seperti komedo (hitam/putih), pustula (berisi nanah), papula (merah tanpa nanah), atau nodul (benjolan besar yang terasa sakit). "
            "Biasanya muncul di wajah, punggung, dan dada, sering kali disebabkan oleh kelebihan produksi minyak, penyumbatan pori-pori, atau perubahan hormon."
        ),
        "Atopic Dermatitis": (
            "Atopic dermatitis, atau eksim atopik, adalah kondisi kulit kronis yang menyebabkan peradangan. "
            "Kulit terasa sangat gatal, merah, kering, dan pecah-pecah. Pada kasus yang parah, bisa menyebabkan cairan keluar dari kulit. "
            "Biasanya terjadi di lipatan tubuh seperti siku, lutut, atau leher. Sering terjadi pada anak-anak, tetapi bisa berlanjut hingga dewasa. "
            "Penyakit ini sering kambuh dan dipicu oleh faktor seperti alergi, stres, cuaca dingin, atau kulit yang terlalu kering."
        ),
        "Herpes": (
            "Herpes adalah infeksi kulit yang disebabkan oleh virus herpes simplex (HSV). Muncul lepuhan kecil berisi cairan yang terasa sakit atau gatal. "
            "Pada herpes oral (HSV-1), lepuhan biasanya muncul di sekitar bibir atau mulut. Pada herpes genital (HSV-2), lepuhan terjadi di area kelamin. "
            "Herpes sering diawali dengan gejala seperti rasa panas atau kesemutan di area yang terinfeksi. "
            "Herpes bersifat menular dan ditularkan melalui kontak langsung dengan luka, cairan tubuh, atau mukosa yang terinfeksi. "
            "Virus ini dapat tetap tidak aktif dalam tubuh dan kambuh akibat stres, penurunan imun, atau paparan sinar matahari."
        ),
        "Psoriasis": (
            "Psoriasis adalah penyakit autoimun kronis yang menyebabkan percepatan regenerasi sel kulit. "
            "Kondisi ini menghasilkan penumpukan sel kulit di permukaan yang terlihat seperti bercak merah dengan sisik keperakan. "
            "Psoriasis sering muncul di area seperti siku, lutut, punggung bawah, atau kulit kepala. "
            "Meskipun tidak menular, penyakit ini dapat memengaruhi kualitas hidup penderitanya dan sering dipicu oleh stres, infeksi, atau luka pada kulit."
        ),
        "Tinea Ringworm": (
            "Tinea ringworm adalah infeksi kulit yang disebabkan oleh jamur dermatofit. Ruam berbentuk cincin dengan tepi bersisik yang menonjol "
            "dan bagian tengahnya sering tampak lebih terang. Penyakit ini dapat menyerang berbagai bagian tubuh, seperti tubuh, kulit kepala, kaki, atau kuku. "
            "Infeksi ini bersifat menular dan biasanya menyebar melalui kontak langsung dengan kulit yang terinfeksi atau benda yang terkontaminasi, seperti handuk, pakaian, atau alat kebersihan."
        ),
        "Wart": (
            "Wart, atau kutil adalah pertumbuhan kulit kecil dan kasar yang disebabkan oleh infeksi virus human papillomavirus (HPV). "
            "Berbentuk benjolan kecil, kasar, dan keras di permukaan kulit. Biasanya muncul di tangan, kaki, atau jari. "
            "Kutil plantar (di telapak kaki) dapat terasa nyeri saat berjalan, sementara kutil kelamin (genital wart) muncul di area genital. "
            "Bentuknya bisa datar, menonjol, atau seperti kembang kol."
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
        "Sedang :Krim atau serum berbasis retinoid atau azelaic acid untuk membantu mengurangi peradangan dan mencegah munculnya lesi baru. Hindari paparan sinar matahari langsung, dan gunakan tabir surya dengan SPF minimal 30.",
        "Ringan :Gunakan pembersih wajah berbahan lembut tanpa alkohol untuk mencegah iritasi. Hindari makanan berminyak atau pedas yang dapat memicu timbulnya jerawat dan rosacea. Gunakan pelembap ringan jika kulit terasa kering.",
        "Parah  :Konsultasikan ke dokter kulit untuk pengobatan oral seperti isotretinoin yang efektif untuk kondisi parah. Dokter juga dapat merekomendasikan perawatan laser atau terapi lain untuk mengurangi kemerahan dan peradangan."
    ],
    "Atopic Dermatitis": [
        "Sedang :Oleskan krim anti-inflamasi seperti kortikosteroid sesuai anjuran dokter untuk mengurangi gatal dan iritasi. Hindari bahan iritan seperti parfum atau kain yang kasar.",
        "Ringan :Gunakan pelembap hypoallergenic secara rutin, terutama setelah mandi, untuk menjaga kelembapan kulit dan mencegah kekeringan. Hindari sabun keras dan gunakan pembersih yang lembut.",
        "Parah  :Jika kondisi memburuk, segera konsultasikan ke dokter untuk mendapatkan pengobatan sistemik seperti imunomodulator atau terapi biologis yang dapat membantu mengendalikan gejala parah."
    ],
    "Herpes": [
        "Sedang :Minum obat antivirus seperti acyclovir atau valacyclovir sesuai resep dokter untuk membantu mempercepat penyembuhan dan mengurangi rasa sakit. Hindari pemicu seperti stres atau kelelahan.",
        "Ringan :Jaga kebersihan area yang terinfeksi dan hindari menyentuh luka untuk mencegah penyebaran. Gunakan kain bersih untuk mengeringkan area tersebut dan hindari berbagi barang pribadi.",
        "Parah  :Segera konsultasikan ke dokter jika luka herpes meluas, terasa sangat nyeri, atau disertai gejala lain seperti demam. Dokter mungkin akan memberikan pengobatan tambahan untuk mengendalikan infeksi."
    ],
    "Psoriasis": [
        "Sedang :Gunakan salep kortikosteroid atau terapi sinar UV yang direkomendasikan dokter untuk membantu mengurangi plak dan peradangan. Ikuti jadwal perawatan secara rutin.",
        "Ringan :Gunakan pelembap tebal untuk mengurangi kekeringan dan ketebalan plak. Hindari pemicu seperti stres, merokok, atau konsumsi alkohol yang dapat memperburuk gejala.",
        "Parah  :Jika kondisi sangat parah, konsultasikan ke dokter untuk mempertimbangkan terapi biologis atau pengobatan sistemik lainnya. Dokter mungkin juga merekomendasikan perawatan intensif di klinik."
    ],
    "Tinea Ringworm": [
        "Sedang :Jika infeksi tidak membaik atau meluas, konsultasikan ke dokter untuk mendapatkan obat antijamur oral. Hindari berbagi barang seperti handuk atau pakaian untuk mencegah penularan.",
        "Ringan :Oleskan obat antijamur topikal seperti clotrimazole atau miconazole secara teratur pada area yang terinfeksi. Pastikan kulit tetap kering dan bersih untuk mencegah penyebaran infeksi.",
        "Parah  :Untuk infeksi yang sangat parah, segera periksakan ke dokter spesialis kulit. Dokter mungkin akan memberikan pengobatan yang lebih kuat atau merekomendasikan tes tambahan untuk memastikan diagnosis."
    ],
    "Wart": [
        "Sedang  :Pertimbangkan krioterapi (pembekuan kutil) di klinik jika kutil tidak merespons pengobatan topikal. Perawatan ini biasanya efektif untuk menghilangkan kutil yang membandel.",
        "Ringan  :Gunakan obat bebas seperti salep asam salisilat secara teratur untuk melunakkan dan menghilangkan kutil kecil. Hindari memotong atau menggaruk kutil untuk mencegah infeksi.",
        "Parah   :Jika kutil besar, nyeri, atau terus menyebar, konsultasikan ke dokter untuk prosedur pembedahan, elektrokoagulasi, atau perawatan laser. Dokter juga dapat memberikan rekomendasi perawatan lanjutan."
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