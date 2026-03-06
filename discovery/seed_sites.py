"""Pure data: seed sites and search queries.

No side effects, no imports beyond models.  Easy to extend by appending
to the two lists below.
"""
from __future__ import annotations

from db.models import Site, Zone, SiteType

SEED_SITES: tuple[Site, ...] = (
    # ── Plataformas de cooperativas ───────────────────────────────────
    Site(url="https://cooptima.es/cooperativas-de-viviendas/madrid",
         name="Cooptima Madrid", zone=Zone.TODAS, site_type=SiteType.PORTAL),
    Site(url="https://aurora-homes.es/cooperativas-de-viviendas-en-madrid/",
         name="Aurora Homes", zone=Zone.TODAS, site_type=SiteType.PORTAL),
    Site(url="https://concovi.org/",
         name="CONCOVI", zone=Zone.TODAS, site_type=SiteType.PORTAL),
    # ── Portales inmobiliarios ────────────────────────────────────────
    Site(url="https://www.idealista.com/obra-nueva/madrid/norte/",
         name="Idealista Obra Nueva Norte", zone=Zone.NORTE, site_type=SiteType.PORTAL),
    Site(url="https://www.idealista.com/obra-nueva/madrid/este/",
         name="Idealista Obra Nueva Este", zone=Zone.ESTE, site_type=SiteType.PORTAL),
    Site(url="https://www.idealista.com/obra-nueva/madrid/oeste/",
         name="Idealista Obra Nueva Oeste", zone=Zone.OESTE, site_type=SiteType.PORTAL),
    Site(url="https://www.fotocasa.es/es/obra-nueva/viviendas/madrid-capital/todas-las-zonas/l",
         name="Fotocasa Obra Nueva Madrid", zone=Zone.TODAS, site_type=SiteType.PORTAL),
    Site(url="https://www.pisos.com/obra-nueva/pisos-madrid/",
         name="Pisos.com Obra Nueva Madrid", zone=Zone.TODAS, site_type=SiteType.PORTAL),
    # ── Cooperativas conocidas ────────────────────────────────────────
    Site(url="https://www.grupovia.net/",
         name="Grupo Via", zone=Zone.TODAS, site_type=SiteType.COOPERATIVA),
    Site(url="https://www.lacooperativadecaballeromejor.com/",
         name="Cooperativa Caballero Mejor", zone=Zone.TODAS, site_type=SiteType.COOPERATIVA),
    # ── Constructoras ─────────────────────────────────────────────────
    Site(url="https://www.aelca.es/viviendas/madrid/",
         name="Aelca Madrid", zone=Zone.NORTE, site_type=SiteType.CONSTRUCTORA),
    Site(url="https://www.metrovacesa.com/promociones-obra-nueva/madrid",
         name="Metrovacesa Madrid", zone=Zone.TODAS, site_type=SiteType.CONSTRUCTORA),
    Site(url="https://www.neinorhomes.com/promociones/madrid/",
         name="Neinor Homes Madrid", zone=Zone.TODAS, site_type=SiteType.CONSTRUCTORA),
    Site(url="https://www.viacelere.com/obra-nueva/madrid",
         name="Via Celere Madrid", zone=Zone.TODAS, site_type=SiteType.CONSTRUCTORA),
    Site(url="https://www.habitatinmobiliaria.com/viviendas/madrid/",
         name="Habitat Inmobiliaria Madrid", zone=Zone.ESTE, site_type=SiteType.CONSTRUCTORA),
    Site(url="https://www.arpada.es/promociones/",
         name="Arpada Promociones", zone=Zone.OESTE, site_type=SiteType.CONSTRUCTORA),
)

SEARCH_QUERIES: tuple[dict[str, str], ...] = (
    {"query": "cooperativa vivienda Madrid norte 2025 2026 site:.es", "zone": "norte"},
    {"query": "cooperativa vivienda Madrid este Vallecas Rivas 2025 site:.es", "zone": "este"},
    {"query": "cooperativa vivienda Madrid oeste Pozuelo Majadahonda 2025 site:.es", "zone": "oeste"},
    {"query": "constructora obra nueva Madrid norte Alcobendas pisos", "zone": "norte"},
    {"query": "constructora obra nueva Madrid este Coslada Torrejon pisos", "zone": "este"},
    {"query": "constructora obra nueva Madrid oeste Boadilla Villanueva pisos", "zone": "oeste"},
    {"query": "nueva promocion vivienda cooperativa Madrid 2025 2026", "zone": "todas"},
    {"query": "cooperativa vivienda joven Madrid precios accesibles", "zone": "todas"},
    {"query": "promocion pisos obra nueva Madrid norte este oeste", "zone": "todas"},
)
