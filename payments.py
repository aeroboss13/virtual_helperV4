import time
import uuid
from json import loads

from yookassa import Configuration, Payment

Configuration.account_id = '206380'
Configuration.secret_key = 'live_tPsGRmcSZ0BFI44fGPTHTls7odjFGb9MD2a-ysDe6X0'


def create_payment(summ: int, description: str):
    payment = Payment.create({
        "amount": {
            "value": str(summ),
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": "https://t.me/chat_ai_ae_bot"
        },
        "capture": True,
        "description": description
    }, uuid.uuid4())
    return [loads(payment.confirmation.json())["confirmation_url"], loads(payment.json())['id']]





def get_payment_status(id: str):
    response = Payment.find_one(payment_id=id)
    if loads(response.json())['status'] in 'succeeded':
        return True
    else:
        return False


