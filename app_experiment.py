import io
import tensorflow as tf
from tensorflow import keras
import numpy as np
from PIL import Image
import firebase_admin
from firebase_admin import auth, credentials, firestore
from uuid import uuid4
from flask import Flask, request, jsonify
from functools import wraps

# Initialize Firebase Admin SDK
cred = credentials.Certificate('./serviceAccountKey.json')
firebase_admin.initialize_app(cred)

# Initialize Firestore
db = firestore.client()

# Initialize Flask app
app = Flask(__name__)

# Load TensorFlow model
model = keras.models.load_model("./model.h5")
label = ['Pohon Beringin', 'Pohon Bungur', 'Pohon Cassia', 'Pohon Jati', 'Pohon Kenanga', 'Pohon Kerai Payung',
         'Pohon Saga', 'Pohon Trembesi', 'pohon Mahoni', 'pohon Matoa']


def predict_label(img):
    i = np.asarray(img) / 255.0
    i = i.reshape(1, 224, 224, 3)
    pred = model.predict(i)
    result = label[np.argmax(pred)]
    return result


# Middleware for authorization checking
def validate_token(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        authorization = request.headers.get('Authorization')
        if not authorization or not authorization.startswith('Bearer '):
            return jsonify({'error': 'Unauthorized'}), 403

        token = authorization.split('Bearer ')[1]

        try:
            decoded_token = firebase_admin.auth.verify_id_token(token)
            request.user_id = decoded_token['uid']
            request.email = decoded_token['email']
        except firebase_admin.auth.InvalidIdTokenError:
            return jsonify({'error': 'Unauthorized'}), 403
        except firebase_admin.auth.ExpiredIdTokenError:
            return jsonify({"error": "Expired authorization token"}), 401

        return f(*args, **kwargs)

    return decorated_function


@app.route("/predict", methods=["POST"])
@validate_token
def predict():
    file = request.files.get('file')
    if file is None or file.filename == "":
        return jsonify({"error": "no file"}), 400

    # Read image and perform prediction
    image_bytes = file.read()
    img = Image.open(io.BytesIO(image_bytes))
    img = img.resize((224, 224), Image.NEAREST)
    pred_label = predict_label(img)

    # Generate UUID for the document in Firestore
    uuid = str(uuid4())

    # Create data object to be stored in Firestore
    data = {
        'uuid': uuid,
        'user_id': request.user_id,
        'email': request.email,
        'plant': []
    }

    # Check if data already exists in Firestore
    existing_data = list(db.collection('users').where('email', '==', request.email).stream())
    if len(existing_data) > 0:
        existing_doc = existing_data[0]
        existing_labels = existing_doc.get('label', [])
        if isinstance(existing_labels, str):
            existing_labels = [existing_labels]
        existing_labels.append(pred_label)
        existing_doc.reference.update({'label': existing_labels})
    else:
        existing_labels = [pred_label]
        db.collection('users').document(uuid).set({**data, 'label': existing_labels})

    # Prepare the plant object
    plant = {
        'name': pred_label,
        'image_url': ''
    }
    data['plant'].append(plant)

    return jsonify({'message': 'Prediction successful', 'data': data}), 200


# Start the server
if __name__ == '__main__':
    app.run(port=3000)
