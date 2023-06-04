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
            # Get the user object to retrieve the username
            user = firebase_admin.auth.get_user(decoded_token['uid'])
            request.username = user.display_name
        except firebase_admin.auth.InvalidIdTokenError:
            return jsonify({'error': 'Unauthorized'}), 403
        except firebase_admin.auth.ExpiredIdTokenError:
            return jsonify({"error": "Expired authorization token"}), 401

        return f(*args, **kwargs)
    return decorated_function


@app.route("/register", methods=["POST"])
def register():
    email = request.json.get("email")
    password = request.json.get("password")
    display_name = request.json.get("display_name")

    try:
        user = auth.create_user(
            email=email,
            password=password,
            display_name=display_name
        )
        return jsonify({"error": False, "message": "Registration successful"}), 200
    except Exception as e:
        error_message = str(e)
        return jsonify({'error': 'Registration failed', 'message': error_message}), 400

@app.route("/predict", methods=["POST"])
@validate_token
def predict():
    file = request.files.get('file')
    if file is None or file.filename == "":
        return jsonify({"error": True, "message": "No file"}), 400

    # Read image and perform prediction
    image_bytes = file.read()
    img = Image.open(io.BytesIO(image_bytes))
    img = img.resize((224, 224), Image.NEAREST)
    pred_label = predict_label(img)

    # Generate UUID for the document in Realtime Database
    uuid = str(uuid4())

    # Check if data already exists in Realtime Database
    existing_data = db.reference('users').order_by_child('user_id').equal_to(request.user_id).get()

    if existing_data:
        # Get the key of the first matching data (assuming there is only one)
        existing_key = list(existing_data.keys())[0]
        # Get the existing plant list
        existing_plant_list = existing_data[existing_key].get('plant', [])
        if isinstance(existing_plant_list, dict):
            existing_plant_list = [existing_plant_list]
        # Determine the index for the new plant
        new_plant_index = len(existing_plant_list)

        # Create data object to be stored in Realtime Database with the new plant
        data = {
            'uuid': uuid,
            'user_id': request.user_id,
            'email': request.email,
            'name': request.username,
            'plant': [
                {
                    'index': new_plant_index,
                    'image_url': '',
                    'name': pred_label
                }
            ]
        }

        # Add the new plant to the existing plant list
        existing_plant_list.append(data['plant'][0])

        # Update the existing data with the updated plant list
        db.reference('users/' + existing_key).update({'plant': existing_plant_list})

        # Update the index of existing plants in the list
        for i, plant in enumerate(existing_plant_list):
            plant['index'] = i

        # Update the data object with the updated plant list
        data['plant'] = existing_plant_list

    else:
        # Create data object to be stored in Realtime Database with initial plant
        data = {
            'uuid': uuid,
            'user_id': request.user_id,
            'email': request.email,
            'name': request.username,
            'plant': [
                {
                    'index': 0,
                    'image_url': '',
                    'name': pred_label
                }
            ]
        }

        # Save data to Realtime Database
        db.reference('users/' + uuid).set(data)

    # Create the response data
    response_data = {
        'data': data,
        'message': 'Success',
        'error': False,
    }

    return jsonify(response_data), 200


@app.route("/user/<user_id>", methods=["GET"])
@validate_token
def get_user_data(user_id):
    # Check if user ID matches the authenticated user
    if user_id != request.user_id:
        return jsonify({"error": True, "message": "Unauthorized"}), 403

    # Retrieve user data from Realtime Database
    user_data = db.reference('users').order_by_child('user_id').equal_to(user_id).get()

    if user_data:
        # Get the key of the first matching user data (assuming there is only one)
        user_key = list(user_data.keys())[0]
        # Retrieve the plant list for the user
        plant_list = user_data[user_key].get('plant', [])

        if isinstance(plant_list, dict):
            plant_list = [plant_list]

        # Update the index values of the plant list to match the Realtime Database
        for i, plant in enumerate(plant_list):
            plant['index'] = i

        response_data = {
            'message': 'User retrieved successfully',
            'error': False,
            'data': {
                'user_id': user_id,
                'email': request.email,
                'name': request.username,
                'plant': plant_list
            }
        }

        return jsonify(response_data), 200
    else:
        return jsonify({"error": True, "message": "User not found"}), 404
    

@app.route("/user/<user_id>/plant/<int:plant_index>", methods=["DELETE"])
@validate_token
def delete_plant(user_id, plant_index):
    # Check if user ID matches the authenticated user
    if user_id != request.user_id:
        return jsonify({"error": True, "message": "Unauthorized"}), 403

    # Retrieve user data from Realtime Database
    user_data = db.reference('users').order_by_child('user_id').equal_to(user_id).get()

    if user_data:
        # Get the key of the first matching user data (assuming there is only one)
        user_key = list(user_data.keys())[0]
        # Retrieve the plant list for the user
        plant_list = user_data[user_key].get('plant', [])

        if isinstance(plant_list, dict):
            plant_list = [plant_list]

        # Check if the provided plant index is valid
        if plant_index < 0 or plant_index >= len(plant_list):
            return jsonify({"error": True, "message": "Invalid plant index"}), 400

        # Remove the plant at the specified index
        deleted_plant = plant_list.pop(plant_index)

        # Update the index values of the remaining plants in the list
        for i, plant in enumerate(plant_list):
            plant['index'] = i

        # Update the plant list in the user's data
        db.reference('users/' + user_key).update({'plant': plant_list})

        response_data = {
            'message': 'Plant deleted',
            'error': False,
            'data': deleted_plant
        }

        return jsonify(response_data), 200
    else:
        return jsonify({"error": True, "message": "User not found"}), 404


@app.route("/user/<user_id>/plants", methods=["GET"])
@validate_token
def get_plants(user_id):
    # Check if user ID matches the authenticated user
    if user_id != request.user_id:
        return jsonify({"error": True, "message": "Unauthorized"}), 403

    # Retrieve user data from Realtime Database
    user_data = db.reference('users').order_by_child('user_id').equal_to(user_id).get()

    if user_data:
        # Get the key of the first matching user data (assuming there is only one)
        user_key = list(user_data.keys())[0]
        # Retrieve the plant list for the user
        plant_list = user_data[user_key].get('plant', [])

        if isinstance(plant_list, dict):
            plant_list = [plant_list]

        # Update the index values of the plant list to match the Realtime Database
        for i, plant in enumerate(plant_list):
            plant['index'] = i

        if len(plant_list) == 0:
            return jsonify({"message": "No plants found", "error": False, "data": []}), 200

        response_data = {
            'message': 'Plants retrieved successfully',
            'error': False,
            'data': plant_list
        }

        return jsonify(response_data), 200
    else:
        return jsonify({"error": True, "message": "User not found"}), 404


# Start the server
if __name__ == '__main__':
    app.run(port=3000)


