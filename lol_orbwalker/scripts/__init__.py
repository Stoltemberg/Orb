from scripts.cassiopeia import CassiopeiaScript
from scripts.kaisa import KaisaScript
from scripts.vayne import VayneScript

def get_script(champ_name: str, riot_api, champ_data):
    """Factory para retornar o script correto dependendo do campeão."""
    champ_name = champ_name.lower()
    
    if "cassiopeia" in champ_name:
        return CassiopeiaScript(riot_api, champ_data)
    
    if "kaisa" in champ_name:
        return KaisaScript(riot_api, champ_data)
        
    if "vayne" in champ_name:
        return VayneScript(riot_api, champ_data)
        
    return None
