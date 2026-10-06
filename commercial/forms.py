from django import forms
from .models import InteresseComercial, PlanoComercial


class InteresseForm(forms.ModelForm):
    plano = forms.ModelChoiceField(queryset=PlanoComercial.objects.none(),required=False,empty_label='Quero conhecer os planos',to_field_name='slug')
    consentimento = forms.BooleanField(label='Autorizo o contato sobre esta solicitação e li as informações de privacidade.')
    website = forms.CharField(required=False,widget=forms.HiddenInput())
    token = forms.CharField(widget=forms.HiddenInput())

    class Meta:
        model = InteresseComercial
        fields = ['plano','periodicidade','nome','empresa','email','telefone','objetivo','mensagem','consentimento']
        labels = {'nome':'Seu nome','empresa':'Nome da empresa','email':'E-mail profissional','telefone':'Telefone / WhatsApp (opcional)','objetivo':'O que você quer organizar?','mensagem':'Conte um pouco sobre sua operação (opcional)','periodicidade':'Periodicidade de interesse'}
        widgets = {'mensagem':forms.Textarea(attrs={'rows':3}),
                   'nome':forms.TextInput(attrs={'autocomplete':'name'}),
                   'empresa':forms.TextInput(attrs={'autocomplete':'organization'}),
                   'email':forms.EmailInput(attrs={'autocomplete':'email'}),
                   'telefone':forms.TextInput(attrs={'type':'tel','autocomplete':'tel'})}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['plano'].queryset=PlanoComercial.objects.filter(ativo=True)
        for key,field in self.fields.items():
            field.widget.attrs.setdefault('class','form-control')
            if key in self.errors:
                field.widget.attrs.update({'aria-invalid':'true','aria-describedby':key+'-errors'})

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()

    def clean(self):
        data=super().clean()
        if data.get('website'):
            raise forms.ValidationError('Não foi possível enviar. Revise os campos e tente novamente.')
        plan=data.get('plano')
        if plan and plan.periodicidade=='ANUAL' and data.get('periodicidade')=='MENSAL':
            self.add_error('periodicidade','Este plano tem preço anual. Selecione anual para solicitar uma proposta.')
        return data
