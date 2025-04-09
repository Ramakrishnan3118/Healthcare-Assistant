import os
import json
import ast
import traceback
from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from langchain.memory import ConversationBufferMemory
from langchain.chat_models import ChatOpenAI
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate

from db.chat_database import engine, get_db
from db.models import Base, Appointment

# Load environment variables from .env
load_dotenv()  # Fetch API keys from .env file
openai_api_key = os.getenv("OPENAI_API_KEY")

# Create the necessary tables in the database
Base.metadata.create_all(engine)

app = FastAPI()

conversation_prompt = PromptTemplate(
    input_variables=["previous_conversations", "user_input"],
    template=""" 
    You are an AI assistant that handles hospital appointment scheduling. Your task is to gather the following information from the user:
    
    - Doctor's specialty (e.g., Cardiologist, Dentist) or the medical issue the user is facing.
    - The date of the appointment (in YYYY-MM-DD format).
    - The time for the appointment (in HH:MM format).

    If the user mentions a health issue, suggest a corresponding doctor.

    If any information is missing, prompt the user for more details.

    If all the required details are collected, reply with the following format:
    {{
        "doctor": "Doctor's Name",
        "date": "YYYY-MM-DD",
        "time": "HH:MM"
    }}

    If the user hasn't provided all necessary details, respond with:
    {{
        "info_required": "Please ask for the missing details."
    }}

    Conversation History:
    {previous_conversations}

    User: {user_input}
    """
)

# Initialize the OpenAI model and set up memory
openai_model = ChatOpenAI(model_name="gpt-4o", openai_api_key=openai_api_key)

conversation_memory = ConversationBufferMemory(memory_key="previous_conversations", return_messages=True)

# Set up the conversation chain with the model and prompt
conversation_chain = LLMChain(
    llm=openai_model,
    prompt=conversation_prompt,
    memory=conversation_memory
)

@app.post("/chat")
def handle_user_input(user_input: str, db: Session = Depends(get_db)):
    """
    AI-powered chatbot to assist users with scheduling or canceling appointments.
    """
    try:
        
        response_from_model = conversation_chain.run(user_input)

        print(response_from_model)

        
        if 'json' in response_from_model:
            response_from_model = response_from_model[7:-3]

        
        try:
            parsed_response = eval(response_from_model)
        except:
            return {"response": "Sorry, I couldn't understand your request. Could you please rephrase?"}

        if "info_required" in parsed_response:
            return {"response": parsed_response["info_required"]}

        doctor_name = parsed_response.get("doctor")
        appointment_date = parsed_response.get("date")
        appointment_time = parsed_response.get("time")

        if "cancel" in user_input.lower():
            appointment_to_cancel = db.query(Appointment).filter_by(
                doctor_name=doctor_name, 
                appointment_date=f"{appointment_date} {appointment_time}",
                status="Scheduled"
            )

            if appointment_to_cancel.first():
                appointment_to_cancel.update({
                    "status": "Cancelled"
                })
                db.commit()
                conversation_memory.clear()
                return {"response": f"Your appointment with Dr. {doctor_name} on {appointment_date} at {appointment_time} has been cancelled successfully."}
            else:
                return {"response": "No scheduled appointment found to cancel at the specified time."}

        conflicting_appointment = db.query(Appointment).filter_by(
            doctor_name=doctor_name, 
            appointment_date=f"{appointment_date} {appointment_time}",
            status="Scheduled"
        ).first()

        if conflicting_appointment:
            return {"response": "This time slot is already taken. Please select a different time."}

        new_appointment_record = Appointment(
            patient_name="User", 
            doctor_name=doctor_name, 
            appointment_date=f"{appointment_date} {appointment_time}"
        )
        db.add(new_appointment_record)
        db.commit()

        conversation_memory.clear()

        return {"response": f"Your appointment with Dr. {doctor_name} has been successfully scheduled for {appointment_date} at {appointment_time}."}

    except Exception as e:
        traceback.print_exc()
        return {"response": "An error occurred. Please try again later."}
