import os
import io
import tensorflow as tf
from tensorflow import keras
import numpy as np
from PIL import Image
import firebase_admin
from firebase_admin import auth, credentials, db
from uuid import uuid4
from flask import Flask, request, jsonify
from functools import wraps
# Initialize Firebase Admin SDK
cred = credentials.Certificate('./serviceAccountKey.json')
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://jejak-karbon-bangkit23-default-rtdb.asia-southeast1.firebasedatabase.app/'
})

# Initialize Flask app
app = Flask(__name__)

# Load TensorFlow model
model = keras.models.load_model("./model.h5")
label = ['Pohon Beringin','Pohon Bungur','Pohon Cassia','Pohon Jati','Pohon Kenanga','Pohon Kerai Payung','Pohon Saga','Pohon Trembesi','pohon Mahoni','pohon Matoa']

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

    # Generate UUID for the document in Realtime Database
    uuid = str(uuid4())

    # Create data object to be stored in Realtime Database
    data = {
        'uuid': uuid,
        'user_id': request.user_id,
        'email': request.email,
        'plant': [
            {
                'image_url': '',
                'name': pred_label
            }
        ]
    }

    # Check if data already exists in Realtime Database
    existing_data = db.reference('users').order_by_child('email').equal_to(request.email).get()
    if existing_data:
        # Get the key of the first matching data (assuming there is only one)
        existing_key = list(existing_data.keys())[0]
        # Get the existing plant list
        existing_plant_list = existing_data[existing_key].get('plant', [])
        if isinstance(existing_plant_list, dict):
            existing_plant_list = [existing_plant_list]
        # Add the new plant to the existing plant list
        existing_plant_list.append({'image_url': '', 'name': pred_label})
        # Update the existing data with the updated plant list
        db.reference('users/' + existing_key).update({'plant': existing_plant_list})
        # Update the data object with the updated plant list
        data['plant'] = existing_plant_list

    else:
        # Save data to Realtime Database with initial plant
        db.reference('users/' + uuid).set({**data, 'plant': data['plant']})

    # Create the response data
    response_data = {
        'data': data,
        'message': 'Prediction successful'
    }

    return jsonify(response_data), 200






# Start the server
if __name__ == '__main__':
    app.run(port=3000)


