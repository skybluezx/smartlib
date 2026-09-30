from pathlib import Path
from prepare_research_classification_sources import fetch

root = Path('outputs/research_classification_20260909/sources')
for url, path in [
    ('https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/qual2026.xml', root / 'qual2026.xml'),
    ('https://incites.zendesk.com/hc/en-gb/article_attachments/24618239025425', root / 'incites_wos_research_areas.xlsx'),
    ('https://incites.zendesk.com/hc/en-gb/articles/22586272202513-Web-of-Science-Research-Areas', root / 'incites_wos_definition.html'),
]:
    receipt = fetch(url, path)
    print(path.name, receipt['bytes'], receipt['sha256'])
