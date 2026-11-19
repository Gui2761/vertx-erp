"""
Gerador de Código de Barras CODE 128 em SVG Vetorial Nativo.
100% Python puro, sem dependências de pacotes externos ou C-extensions.
Gera SVGs ultra-nítidos e perfeitamente legíveis por leitores ópticos e lasers.
"""

# Padrões de larguras (barra, espaço, barra, espaço, barra, espaço) para valores de 0 a 106
_PATTERNS = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
    "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
    "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
    "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
    "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
    "231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
    "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
    "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
    "114131", "311141", "411131", "211412", "211214", "211232", "2331112"
]

START_B = 104
STOP = 106

def generate_code128_svg(text, height=45, module_width=1.5, include_text=True):
    """
    Gera código de barras CODE 128 (Subset B) em formato SVG.
    
    :param text: Texto ou número a ser codificado.
    :param height: Altura das barras em pixels (padrão: 45).
    :param module_width: Largura de cada módulo em pixels (padrão: 1.5).
    :param include_text: Se True, renderiza o texto legível abaixo das barras.
    :return: String contendo o SVG completo.
    """
    clean_text = str(text).strip()
    if not clean_text:
        return ""
        
    values = [START_B]
    for char in clean_text:
        code = ord(char) - 32
        if 0 <= code <= 95:
            values.append(code)
        else:
            values.append(ord('?') - 32)
            
    # Cálculo do Checksum
    checksum = values[0]
    for i, val in enumerate(values[1:], start=1):
        checksum += val * i
    values.append(checksum % 103)
    values.append(STOP)
    
    # Desenhar barras
    rects = []
    current_x = 10.0  # Margem inicial (quiet zone)
    
    for val in values:
        pattern = _PATTERNS[val]
        is_bar = True
        for width_char in pattern:
            w = int(width_char) * module_width
            if is_bar:
                rects.append(f'<rect x="{current_x:.1f}" y="0" width="{w:.1f}" height="{height}" fill="#000000" />')
            current_x += w
            is_bar = not is_bar
            
    total_width = current_x + 10.0  # Margem final
    total_height = height + (14 if include_text else 0)
    
    text_element = ""
    if include_text:
        center_x = total_width / 2.0
        text_y = height + 11
        text_element = f'<text x="{center_x:.1f}" y="{text_y}" font-family="monospace" font-size="10" font-weight="bold" text-anchor="middle" fill="#000000">{clean_text}</text>'
        
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_width:.1f} {total_height:.1f}" '
        f'width="{total_width:.1f}" height="{total_height:.1f}" style="display:block; margin:0 auto;">'
        + "".join(rects)
        + text_element
        + '</svg>'
    )
    return svg
