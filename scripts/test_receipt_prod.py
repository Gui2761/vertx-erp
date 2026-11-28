import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tecnolmed.settings')
django.setup()

from operacao.models import Venda
from operacao.pdv import sale
from django.test import RequestFactory
from django.contrib.auth import get_user_model

v = Venda.objects.filter(public_id='fb78be66-cd63-4f5c-99bc-4d32b6fa774c').first()
print('Venda encontrada:', v)

if v:
    rf = RequestFactory()
    req = rf.get(f'/pdv/vendas/{v.public_id}/comprovante/')
    u = get_user_model().objects.filter(is_superuser=True).first()
    req.user = u
    res = sale(req, v.public_id, receipt=True)
    print('RECEIPT_STATUS_CODE:', res.status_code)
    print('Conteudo tamanho:', len(res.content))
else:
    # Test any sale or recent sale
    latest = Venda.objects.order_by('-pk').first()
    print('Ultima venda:', latest)
    if latest:
        rf = RequestFactory()
        req = rf.get(f'/pdv/vendas/{latest.public_id}/comprovante/')
        u = get_user_model().objects.filter(is_superuser=True).first()
        req.user = u
        res = sale(req, latest.public_id, receipt=True)
        print('LATEST_RECEIPT_STATUS_CODE:', res.status_code)
        print('Conteudo tamanho:', len(res.content))
