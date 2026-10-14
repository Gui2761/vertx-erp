"""Versioned schema routing. PL 010f document types remain unmodified.

SOAP lot/receipt wrappers are compiled from the official named types, without
creating or claiming a new official XSD file. Query/event packages have their
own pins and applicability gates, independent of the document release.
"""
from pathlib import Path
from .schema import SchemaOficial
from .contracts import DependenciaFiscal

BASE=Path(__file__).resolve().parent/'schemas'


class SchemaFluxo:
    def __init__(self, *, ensaio_local=False):
        self.ensaio_local=ensaio_local
        self.documento=SchemaOficial(BASE/'PL_010f_v1.04','PL_010f_v1.04')
        self.consulta=SchemaOficial(BASE/'PL_010d_consulta_v1.03','PL_010d_consulta_v1.03')
        self.cancelamento=SchemaOficial(BASE/'Evento_Canc_v1.01','Evento_Canc_v1.01')

    def validar(self,data,nome='nfe_v4.00.xsd'):
        if nome in ('envEventoCancNFe_v1.00.xsd','retEnvEventoCancNFe_v1.00.xsd'):
            return self.cancelamento.validar(data,nome,ensaio_local=self.ensaio_local)
        if nome in ('consSitNFe_v4.00.xsd','retConsSitNFe_v4.00.xsd'):
            return self.consulta.validar(data,nome,ensaio_local=self.ensaio_local)
        types={'enviNFe_v4.00.xsd':'TEnviNFe','retEnviNFe_v4.00.xsd':'TRetEnviNFe',
               'consReciNFe_v4.00.xsd':'TConsReciNFe','retConsReciNFe_v4.00.xsd':'TRetConsReciNFe',
               'procNFe_v4.00.xsd':'TNfeProc'}
        if nome in types:
            return self.documento.validar(data,'leiauteNFe_v4.00.xsd',ensaio_local=self.ensaio_local,tipo=types[nome])
        if nome!='nfe_v4.00.xsd':raise DependenciaFiscal('Schema não cadastrado na atualização controlada.')
        return self.documento.validar(data,nome,ensaio_local=self.ensaio_local)

    def validar_sem_assinatura(self,data,nome='nfe_v4.00.xsd'):
        schema=self.cancelamento if nome=='envEventoCancNFe_v1.00.xsd' else self.documento
        return schema.validar_sem_assinatura(data,nome,ensaio_local=self.ensaio_local)
