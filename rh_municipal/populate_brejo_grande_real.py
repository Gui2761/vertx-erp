import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import django
import decimal
from datetime import date, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tecnolmed.test_settings')
django.setup()

from django.utils import timezone
from platform_core.models import Organization, OrganizationMembership
from platform_core.context import tenant_context
from contas.models import Usuario
from rh_municipal.models import (
    PerfilPrefeitura, Secretaria, DepartamentoMunicipal, SetorMunicipal, UnidadeMunicipal,
    CargoMunicipal, Servidor, VinculoFuncional,
    UnidadeSaudeMunicipal, EquipeSaudeMunicipal, ProfissionalSaudeMunicipal,
    CidadaoSaudeMunicipal, FamiliaTerritorialSaude,
    MedicamentoMunicipal, LoteMedicamentoMunicipal, VisitaTerritorialSaude,
    ServicoFilaSaude, LocalAtendimentoSaude, SenhaFilaAtendimento, ClassificacaoManchester,
    AtendimentoSaudeMunicipal, PrescricaoSaudeMunicipal, ItemPrescricaoSaude,
    DispensacaoMedicamentoMunicipal, ItemDispensacaoSaude
)

def populate():
    print("Iniciando população de dados REAIS para Licitações de Brejo Grande e Poço Redondo...")

    # 1. ADMIN USER
    admin_user, _ = Usuario.objects.get_or_create(
        username='gestor.saude',
        defaults={
            'email': 'gestor.saude@brejogrande.se.gov.br',
            'first_name': 'Gestor',
            'last_name': 'Municipal de Saúde',
            'is_staff': True,
        }
    )
    admin_user.set_password('Admin@123')
    admin_user.save()

    # 2. ORGANIZAÇÃO BREJO GRANDE (Edital Saúde - R$ 611.640,00)
    org_bg, _ = Organization.objects.get_or_create(
        slug='fms-brejo-grande',
        defaults={
            'razao_social': 'FUNDO MUNICIPAL DE SAUDE DE BREJO GRANDE',
            'nome_fantasia': 'Prefeitura Municipal de Brejo Grande / Fundo Municipal de Saúde',
            'cnpj': '13111539000160',
            'email': 'saude@brejogrande.se.gov.br',
            'telefone': '(79) 3366-1122',
            'endereco': 'Praça da Matriz, s/n, Centro',
            'cidade': 'Brejo Grande',
            'uf': 'SE',
            'status': 'ATIVA',
        }
    )

    # 3. ORGANIZAÇÃO POÇO REDONDO (Edital Gestão Digital SaaS - 300 usuários)
    org_pr, _ = Organization.objects.get_or_create(
        slug='pm-poco-redondo',
        defaults={
            'razao_social': 'PREFEITURA MUNICIPAL DE POCO REDONDO',
            'nome_fantasia': 'Prefeitura Municipal de Poço Redondo',
            'cnpj': '13114004000142',
            'email': 'licitacao@pocoredondo.se.gov.br',
            'telefone': '(79) 3337-1307',
            'endereco': 'Avenida Alcino Alves Costa, 363, Centro',
            'cidade': 'Poço Redondo',
            'uf': 'SE',
            'status': 'ATIVA',
        }
    )

    # 4. PERFIL POÇO REDONDO
    with tenant_context(org_pr):
        perfil_pr, _ = PerfilPrefeitura.objects.get_or_create(
            organization=org_pr,
            defaults={
                'nome_institucional': 'Prefeitura Municipal de Poço Redondo',
                'codigo_ibge': '2805407',
                'ativo': True,
            }
        )

    # 5. POVOAMENTO COMPLETO DE BREJO GRANDE NO TENANT CONTEXT
    with tenant_context(org_bg):
        perfil_bg, _ = PerfilPrefeitura.objects.get_or_create(
            organization=org_bg,
            defaults={
                'nome_institucional': 'Prefeitura Municipal de Brejo Grande',
                'codigo_ibge': '2800705',
                'ativo': True,
            }
        )

        sec_saude, _ = Secretaria.objects.get_or_create(
            organization=org_bg,
            sigla='SMS',
            defaults={'nome': 'Secretaria Municipal de Saúde', 'ativo': True}
        )

        dep_ab, _ = DepartamentoMunicipal.objects.get_or_create(
            organization=org_bg,
            secretaria=sec_saude,
            sigla='DAB',
            defaults={'nome': 'Departamento de Atenção Básica', 'ativo': True}
        )

        setor_aps, _ = SetorMunicipal.objects.get_or_create(
            organization=org_bg,
            secretaria=sec_saude,
            departamento=dep_ab,
            sigla='APS',
            defaults={'nome': 'Setor de Atenção Primária à Saúde', 'ativo': True}
        )

        unidade_mun, _ = UnidadeMunicipal.objects.get_or_create(
            organization=org_bg,
            secretaria=sec_saude,
            departamento=dep_ab,
            setor=setor_aps,
            sigla='UBS-MPS',
            defaults={
                'nome': 'Unidade Básica de Saúde Maria Pureza da Silva',
                'logradouro': 'Rua do Campo',
                'numero': '120',
                'bairro': 'Centro',
                'cep': '49990-000',
                'ativo': True,
            }
        )

        ubs, _ = UnidadeSaudeMunicipal.objects.get_or_create(
            organization=org_bg,
            unidade=unidade_mun,
            defaults={'tipo': 'UBS', 'cnes': '2498712', 'servicos': 'Atenção Primária, Vacinação, Odontologia, Farmácia'}
        )

        # SERVIÇOS NOVO SGA
        servicos_specs = [
            ('CLN', 'Clínica Médica Geral', 'Consultas médicas de clínica geral e acolhimento', 'stethoscope', 1),
            ('ENF', 'Enfermagem e Procedimentos', 'Triagem de risco, curativos, verificação de sinais e acolhimento', 'heart-pulse', 2),
            ('ODO', 'Saúde Bucal / Odontologia', 'Atendimento odontológico de atenção primária', 'smile', 3),
            ('VAC', 'Sala de Vacinação', 'Imunização do calendário nacional de vacinação do SUS', 'shield', 4),
            ('FAR', 'Farmácia Básica Municipal', 'Dispensação de medicamentos essenciais RENAME / Hórus', 'package', 5),
            ('PRE', 'Pré-Natal e Saúde da Mulher', 'Consultas obstétricas, preventivo e acompanhamento puerperal', 'user-check', 6),
        ]

        servicos_map = {}
        for cod, nome, desc, icon, ord_num in servicos_specs:
            s, _ = ServicoFilaSaude.objects.get_or_create(
                organization=org_bg,
                unidade_saude=ubs,
                codigo=cod,
                defaults={'nome': nome, 'descricao': desc, 'icone': icon, 'ordem': ord_num, 'ativo': True}
            )
            servicos_map[cod] = s

        # LOCAIS DE ATENDIMENTO
        locais_specs = [
            ('CONSULTORIO', 1, 'Consultório 01 - Dr. Carlos Eduardo (Clínica Geral)'),
            ('CONSULTORIO', 2, 'Consultório 02 - Dra. Mariana Costa (Saúde da Família)'),
            ('ODONTOLOGIA', 1, 'Consultório Odontológico - Dr. Roberto Almeida'),
            ('TRIAGEM', 1, 'Sala de Triagem e Acolhimento Manchester'),
            ('SALA_VACINA', 1, 'Sala de Vacinas e Imunização'),
            ('FARMACIA', 1, 'Farmácia Municipal - Guichê 01'),
        ]

        locais_map = {}
        for tipo, num, nome in locais_specs:
            l, _ = LocalAtendimentoSaude.objects.get_or_create(
                organization=org_bg,
                unidade_saude=ubs,
                tipo=tipo,
                numero=num,
                defaults={'nome': nome, 'ativo': True}
            )
            locais_map[f"{tipo}_{num}"] = l

        # EQUIPE ESF
        equipe_esf, _ = EquipeSaudeMunicipal.objects.get_or_create(
            organization=org_bg,
            unidade_saude=ubs,
            codigo_ine='0001428590',
            defaults={'nome': 'Equipe de Saúde da Família 01 - Centro', 'tipo': 'ESF', 'ativo': True}
        )

        # CARGOS
        cargo_med, _ = CargoMunicipal.objects.get_or_create(organization=org_bg, codigo='MED-ESF', defaults={'nome': 'Médico de Saúde da Família', 'ativo': True})
        cargo_enf, _ = CargoMunicipal.objects.get_or_create(organization=org_bg, codigo='ENF-APS', defaults={'nome': 'Enfermeiro de Atenção Primária', 'ativo': True})
        cargo_dent, _ = CargoMunicipal.objects.get_or_create(organization=org_bg, codigo='CD-APS', defaults={'nome': 'Cirurgião-Dentista', 'ativo': True})
        cargo_farm, _ = CargoMunicipal.objects.get_or_create(organization=org_bg, codigo='FARM-MUN', defaults={'nome': 'Farmacêutico Bioquímico', 'ativo': True})
        cargo_acs, _ = CargoMunicipal.objects.get_or_create(organization=org_bg, codigo='ACS-TERR', defaults={'nome': 'Agente Comunitário de Saúde', 'ativo': True})

        profissionais_specs = [
            ('Dr. Carlos Eduardo Santos', 'MED', 'CRM/SE', '4821', 'Clínica Geral / APS', cargo_med),
            ('Dra. Mariana Costa Lima', 'MED', 'CRM/SE', '5219', 'Medicina de Família e Comunidade', cargo_med),
            ('Enfª. Juliana Silveira Ramos', 'ENF', 'COREN/SE', '18452-ENF', 'Enfermagem de Saúde Pública', cargo_enf),
            ('Dr. Roberto Almeida Prado', 'ODON', 'CRO/SE', '2981', 'Saúde Bucal Coletiva', cargo_dent),
            ('Farmª. Beatriz Vasconcelos', 'FARM', 'CRF/SE', '3120', 'Assistência Farmacêutica Básica', cargo_farm),
            ('ACS Joana Dark de Oliveira', 'ACS', 'MS/ACS', '28007-01', 'Atenção Primária / Microárea 01', cargo_acs),
            ('ACS Marcos Vinícius Dantas', 'ACS', 'MS/ACS', '28007-02', 'Atenção Primária / Microárea 02', cargo_acs),
        ]

        prof_map = {}
        for nome_prof, ocup, conselho, reg, esp, cargo in profissionais_specs:
            user_p, _ = Usuario.objects.get_or_create(
                username=f"prof.{reg.replace('/', '_').lower()}",
                defaults={'email': f"prof_{reg.replace('/', '_').lower()}@brejogrande.se.gov.br", 'first_name': nome_prof.split()[0], 'last_name': ' '.join(nome_prof.split()[1:])}
            )
            serv, _ = Servidor.objects.get_or_create(
                organization=org_bg,
                matricula=f"M-{reg.replace('/', '')[-5:]}",
                defaults={'nome': nome_prof, 'cargo': cargo, 'ativo': True}
            )
            prof, _ = ProfissionalSaudeMunicipal.objects.get_or_create(
                organization=org_bg,
                servidor=serv,
                unidade_saude=ubs,
                defaults={'equipe': equipe_esf, 'ocupacao': ocup, 'conselho': conselho, 'registro_conselho': reg, 'especialidade': esp, 'ativo': True}
            )
            prof_map[ocup] = prof

        # PACIENTES
        pacientes_specs = [
            ('José da Silva Santos', '02145878512', '700012345678901', date(1978, 5, 14), '(79) 99876-1101', 'Rua Nova, 45, Centro'),
            ('Maria Auxiliadora dos Santos', '34189012345', '700098765432109', date(1995, 8, 22), '(79) 99876-1102', 'Povoado Saramém, 12'),
            ('Antônio Ferreira Lima', '11233455678', '700054321678902', date(1958, 11, 3), '(79) 99876-1103', 'Rua do Campo, 88'),
            ('Francisca das Chagas Oliveira', '45678901234', '700087654321098', date(1954, 3, 30), '(79) 99876-1104', 'Avenida Beira Rio, 210'),
            ('Pedro Henrique Menezes', '56789012345', '700034567890123', date(2018, 9, 12), '(79) 99876-1105', 'Rua da Areia, 56'),
        ]

        cid_map = []
        for nome_pac, cpf, cns, dt_nasc, fone, end in pacientes_specs:
            c, _ = CidadaoSaudeMunicipal.objects.get_or_create(
                organization=org_bg,
                cpf=cpf,
                defaults={
                    'cns': cns,
                    'nome': nome_pac,
                    'data_nascimento': dt_nasc,
                    'telefone': fone,
                    'endereco': end,
                    'bairro': 'Centro',
                    'municipio': 'Brejo Grande',
                    'uf': 'SE',
                    'situacao': 'ATIVO',
                }
            )
            cid_map.append(c)

        # MEDICAMENTOS RENAME E LOTES HÓRUS
        meds_specs = [
            ('MED-001', 'Losartana Potássica', '50 mg Comprimido', 'Comprimido', decimal.Decimal('500.000'), 'LT2026-A1', date(2026, 12, 31), decimal.Decimal('1500.000')),
            ('MED-002', 'Metformina Cloridrato', '850 mg Comprimido', 'Comprimido', decimal.Decimal('300.000'), 'LT2026-B2', date(2026, 11, 30), decimal.Decimal('980.000')),
            ('MED-003', 'Amoxicilina', '500 mg Cápsula', 'Cápsula', decimal.Decimal('200.000'), 'LT2027-C3', date(2027, 4, 30), decimal.Decimal('600.000')),
            ('MED-004', 'Dipirona Sódica', '500 mg/mL Gotas Frasco 10mL', 'Frasco', decimal.Decimal('100.000'), 'LT2026-D4', date(2026, 9, 30), decimal.Decimal('450.000')),
            ('MED-005', 'Omeprazol', '20 mg Cápsula', 'Cápsula', decimal.Decimal('400.000'), 'LT2026-E5', date(2026, 10, 31), decimal.Decimal('1100.000')),
            ('MED-006', 'Insulina Humana NPH', '100 UI/mL Suspensão Injetável 10mL', 'Frasco-Ampola', decimal.Decimal('50.000'), 'LT2026-F6', date(2026, 8, 31), decimal.Decimal('180.000')),
        ]

        for cod, nome, apr, un, est_min, num_lote, val_dt, saldo in meds_specs:
            med, _ = MedicamentoMunicipal.objects.get_or_create(
                organization=org_bg,
                codigo=cod,
                defaults={'nome': nome, 'apresentacao': apr, 'unidade_medida': un, 'estoque_minimo': est_min, 'ativo': True}
            )
            LoteMedicamentoMunicipal.objects.get_or_create(
                organization=org_bg,
                medicamento=med,
                unidade_saude=ubs,
                lote=num_lote,
                defaults={'validade': val_dt, 'saldo': saldo}
            )

        # SENHAS DA FILA NOVO SGA
        agora = timezone.now()
        senhas_specs = [
            ('CLN', 1, 'CONVENCIONAL', '', 'CLN-001', 'ENCERRADA', cid_map[0], locais_map['CONSULTORIO_1'], prof_map['MED'], agora - timedelta(minutes=45), agora - timedelta(minutes=40), agora - timedelta(minutes=38), agora - timedelta(minutes=15)),
            ('ENF', 1, 'PRIORITARIA', 'Idoso 60+', 'ENF-P001', 'ENCERRADA', cid_map[3], locais_map['TRIAGEM_1'], prof_map['ENF'], agora - timedelta(minutes=40), agora - timedelta(minutes=35), agora - timedelta(minutes=33), agora - timedelta(minutes=20)),
            ('CLN', 2, 'CONVENCIONAL', '', 'CLN-002', 'EM_ATENDIMENTO', cid_map[2], locais_map['CONSULTORIO_1'], prof_map['MED'], agora - timedelta(minutes=25), agora - timedelta(minutes=18), agora - timedelta(minutes=15), None),
            ('ODO', 1, 'CONVENCIONAL', '', 'ODO-001', 'CHAMADA', cid_map[4], locais_map['ODONTOLOGIA_1'], prof_map['ODON'], agora - timedelta(minutes=15), agora - timedelta(minutes=2), None, None),
            ('CLN', 3, 'PRIORITARIA', 'Gestante', 'CLN-P003', 'EMITIDA', cid_map[1], None, None, agora - timedelta(minutes=10), None, None, None),
            ('VAC', 1, 'CONVENCIONAL', '', 'VAC-001', 'EMITIDA', cid_map[4], None, None, agora - timedelta(minutes=8), None, None, None),
            ('FAR', 1, 'CONVENCIONAL', '', 'FAR-001', 'EMITIDA', cid_map[0], None, None, agora - timedelta(minutes=5), None, None, None),
        ]

        for s_cod, seq, prio, det, cod_fmt, st, cid, loc, prof, em_em, ch_em, in_em, enc_em in senhas_specs:
            s_obj, _ = SenhaFilaAtendimento.objects.get_or_create(
                organization=org_bg,
                unidade_saude=ubs,
                codigo_formatado=cod_fmt,
                defaults={
                    'servico': servicos_map[s_cod],
                    'cidadao': cid,
                    'local_chamado': loc,
                    'profissional': prof,
                    'numero_sequencial': seq,
                    'tipo_prioridade': prio,
                    'detalhe_prioridade': det,
                    'status': st,
                    'emitida_em': em_em,
                    'chamada_em': ch_em,
                    'iniciada_em': in_em,
                    'encerrada_em': enc_em,
                }
            )

        # TRIAGEM MANCHESTER
        s_triada = SenhaFilaAtendimento.objects.filter(codigo_formatado='CLN-002').first()
        if s_triada:
            ClassificacaoManchester.objects.get_or_create(
                organization=org_bg,
                senha=s_triada,
                defaults={
                    'cidadao': s_triada.cidadao,
                    'enfermeiro': prof_map['ENF'],
                    'fluxograma': 'Cefaleia / Hipertensão Arterial Sistêmica',
                    'discriminador': 'Cefaleia Moderada com PA Elevada',
                    'cor': 'AMARELO',
                    'tempo_alvo_minutos': 60,
                    'pa_sistolica': 160,
                    'pa_diastolica': 100,
                    'frequencia_cardiaca': 86,
                    'frequencia_respiratoria': 18,
                    'temperatura': decimal.Decimal('36.6'),
                    'glicemia': 178,
                    'saturacao_o2': 98,
                    'peso_kg': decimal.Decimal('82.50'),
                    'altura_cm': 172,
                    'queixa_principal': 'Cefaleia occipital pulsátil há 4 horas, em acompanhamento de HAS e DM2.',
                }
            )

        # VISITAS ACS
        fam_1, _ = FamiliaTerritorialSaude.objects.get_or_create(
            organization=org_bg,
            unidade_saude=ubs,
            numero_prontuario='FAM-28007-001',
            defaults={'renda_familiar_estimada': decimal.Decimal('1412.00')}
        )

        visitas_specs = [
            (cid_map[1], 'Gestante 28 semanas - pré-natal e vacina dTpa em dia. Portaria 3.493/2024'),
            (cid_map[2], 'Hipertenso e Diabético - PA aferida 150/95 mmHg, glicemia capilar verificada.'),
            (cid_map[3], 'Idosa acamada - avaliação de mobilidade e estoque de medicamentos contínuos.'),
            (cid_map[0], 'Visita periódica familiar - saneamento e acompanhamento vacinal.'),
        ]

        for cid_v, obs in visitas_specs:
            VisitaTerritorialSaude.objects.get_or_create(
                organization=org_bg,
                cidadao=cid_v,
                agente=prof_map['ACS'],
                defaults={
                    'tipo': 'ACS',
                    'familia': fam_1,
                    'realizada_em': agora - timedelta(days=2),
                    'status': 'REALIZADA',
                }
            )

    print("População de dados REAIS concluída com 100% de sucesso!")
    print(f"Total Senhas: {SenhaFilaAtendimento.all_objects.count()}")
    print(f"Total Pacientes: {CidadaoSaudeMunicipal.all_objects.count()}")
    print(f"Total Serviços Fila: {ServicoFilaSaude.all_objects.count()}")
    print(f"Total Locais: {LocalAtendimentoSaude.all_objects.count()}")
    print(f"Total Medicamentos Lote: {LoteMedicamentoMunicipal.all_objects.count()}")
    print(f"Total Visitas ACS: {VisitaTerritorialSaude.all_objects.count()}")

if __name__ == '__main__':
    populate()
