from fastapi import FastAPI
import boto3

app = FastAPI()

@app.get("/")
def home():
    return {"message": "CloudOps AI is running 🚀"}

@app.get("/ec2")
def list_ec2():
    ec2 = boto3.client("ec2")

    response = ec2.describe_instances()

    instances = []

    for reservation in response["Reservations"]:
        for instance in reservation["Instances"]:
            instances.append({
                "InstanceId": instance["InstanceId"],
                "State": instance["State"]["Name"],
                "InstanceType": instance["InstanceType"]
            })

    return instances