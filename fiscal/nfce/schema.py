"""Offline XSD validation with pinned files. Never fetch schemas while emitting."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname
from lxml import etree
from .contracts import DependenciaFiscal

NFE = 'http://www.portalfiscal.inf.br/nfe'


def local_schema_path(url):
    """Normalize libxml file URIs before comparing to pinned local paths."""
    uri = urlsplit(url)
    if uri.scheme == 'file':
        if uri.netloc:
            raise ValueError('Import remoto proibido.')
        return Path(url2pathname(uri.path)).resolve()
    return Path(url).resolve()


def parse(xml):
    if not isinstance(xml, bytes) or len(xml) > 2_000_000 or b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
        raise DependenciaFiscal('XML inválido ou entidades externas proibidas.')
    try:
        return etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
    except etree.XMLSyntaxError:
        raise DependenciaFiscal('XML malformado; conteúdo não exposto nos logs.')


class SchemaOficial:
    def __init__(self, directory=None, release=''):
        self.directory = Path(directory).resolve() if directory else None
        self.release = release
    def validar(self, xml, nome='nfe_v4.00.xsd', *, ensaio_local=False, tipo=None, sem_assinatura=False):
        if not self.directory or not (self.directory / 'manifest.json').is_file():
            raise DependenciaFiscal('Pacote XSD oficial verificado ausente; emissão bloqueada.')
        try:
            manifest = json.loads((self.directory / 'manifest.json').read_text(encoding='utf-8'))
            source=urlsplit(manifest['fonte'])
            official={'www.nfe.fazenda.gov.br','dfe-portal.svrs.rs.gov.br','www.sefaz.se.gov.br'}
            if ensaio_local:
                from .services import local
                local()
            applicability = manifest['aplicabilidade_confirmada']
            if not applicability and not (ensaio_local and manifest.get('escopo')=='ENSAIO_LOCAL_SINTETICO'):
                raise ValueError()
            if not self.release or manifest['release'] != self.release or source.scheme!='https' or source.hostname not in official or source.username or source.password:
                raise ValueError()
            for name, digest in manifest['sha256'].items():
                path = (self.directory / name).resolve()
                if self.directory not in path.parents or path.suffix != '.xsd' or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError()
            if nome not in manifest['sha256']:
                raise ValueError()
            document = parse(xml)
            if sem_assinatura and document.findall('.//{http://www.w3.org/2000/09/xmldsig#}Signature'):
                raise ValueError()
            parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
            # A resolver restricts all includes/imports to pinned local files.
            directory = self.directory
            files = {(directory / name).resolve() for name in manifest['sha256']}
            class LocalOnly(etree.Resolver):
                def resolve(self, url, public_id, context):
                    path = local_schema_path(url)
                    if path not in files:
                        raise ValueError('Import não verificado.')
                    if sem_assinatura:
                        # Only the unsigned preparation pass omits the mandatory
                        # signature. All fiscal fields retain official types.
                        # Files on disk and the signed validation are unchanged.
                        tree = etree.fromstring(path.read_bytes(), etree.XMLParser(resolve_entities=False, no_network=True))
                        for ref in tree.findall('.//{http://www.w3.org/2001/XMLSchema}element'):
                            if ref.get('ref') == 'ds:Signature':
                                ref.set('minOccurs', '0')
                        return self.resolve_string(etree.tostring(tree), context, base_url=path.as_uri())
                    return self.resolve_filename(str(path), context)
            parser.resolvers.add(LocalOnly())
            if tipo:
                allowed = {'NFe':'TNFe', 'enviNFe':'TEnviNFe', 'retEnviNFe':'TRetEnviNFe',
                           'consReciNFe':'TConsReciNFe', 'retConsReciNFe':'TRetConsReciNFe', 'nfeProc':'TNfeProc',
                           'envEvento':'TEnvEvento', 'retEnvEvento':'TRetEnvEvento'}
                name=etree.QName(document).localname
                if allowed.get(name)!=tipo or etree.QName(document).namespace!=NFE:
                    raise ValueError()
                xs='http://www.w3.org/2001/XMLSchema'
                wrapper=etree.Element('{'+xs+'}schema', nsmap={'xs':xs, 'n':NFE}, targetNamespace=NFE, elementFormDefault='qualified')
                etree.SubElement(wrapper,'{'+xs+'}include',schemaLocation=nome)
                etree.SubElement(wrapper,'{'+xs+'}element',name=name,type='n:'+tipo)
                schema=etree.XMLSchema(etree.fromstring(etree.tostring(wrapper),parser,base_url=(directory/'entry.xsd').as_uri()))
            else:
                schema = etree.XMLSchema(etree.parse(str(self.directory / nome), parser))
            if not schema.validate(document):
                raise DependenciaFiscal('XML não atende ao XSD oficial selecionado; revise os campos fiscais.')
            return {'resultado':'APROVADO', 'release':self.release, 'pacote':manifest.get('pacote',self.release),
                    'arquivo':nome, 'namespace':NFE, 'fonte':manifest['fonte'],
                    'sha256':manifest['sha256'][nome], 'ensaio_local':ensaio_local,
                    'aplicabilidade_sefaz_confirmada':bool(applicability), 'etapa':'ANTES_DA_ASSINATURA' if sem_assinatura else 'INTEGRAL', 'tipo_oficial':tipo}
        except DependenciaFiscal:
            raise
        except (KeyError, ValueError, OSError, etree.LxmlError):
            raise DependenciaFiscal('Pacote XSD inválido, modificado ou incompleto; emissão bloqueada.')

    def validar_sem_assinatura(self, xml, nome='nfe_v4.00.xsd', *, ensaio_local=False):
        return self.validar(xml,nome,ensaio_local=ensaio_local,sem_assinatura=True)
