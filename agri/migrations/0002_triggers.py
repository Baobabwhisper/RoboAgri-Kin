from django.db import migrations

TRIGGERS = {
    # R-M1 : transitions d'état d'une mission autorisées uniquement
    "trg_mission_transition": """
    CREATE TRIGGER trg_mission_transition
    BEFORE UPDATE OF statut ON agri_mission
    WHEN OLD.statut <> NEW.statut AND NOT (
           (OLD.statut = 'PLANIFIEE'     AND NEW.statut IN ('EN_COURS','ANNULEE'))
        OR (OLD.statut = 'EN_COURS'      AND NEW.statut IN ('TERMINEE','INTERROMPUE','NON_CONFIRMEE'))
        OR (OLD.statut = 'NON_CONFIRMEE' AND NEW.statut IN ('TERMINEE','INTERROMPUE'))
    )
    BEGIN SELECT RAISE(ABORT, 'Transition de statut de mission interdite'); END;""",

    # R-M2 : la mesure doit porter sur la zone ET la mission de son étape
    "trg_mesure_coherence_etape": """
    CREATE TRIGGER trg_mesure_coherence_etape
    BEFORE INSERT ON agri_mesure
    WHEN NOT EXISTS (SELECT 1 FROM agri_etapemission
                     WHERE id = NEW.etape_id AND mission_id = NEW.mission_id
                       AND zone_id = NEW.zone_id)
    BEGIN SELECT RAISE(ABORT, 'Mesure incohérente avec l''étape (zone ou mission)'); END;""",

    # R-M3 : pas de mesure sur une mission non démarrée ou annulée
    "trg_mesure_mission_active": """
    CREATE TRIGGER trg_mesure_mission_active
    BEFORE INSERT ON agri_mesure
    WHEN (SELECT statut FROM agri_mission WHERE id = NEW.mission_id) IN ('PLANIFIEE','ANNULEE')
    BEGIN SELECT RAISE(ABORT, 'Mesure refusée : mission non démarrée ou annulée'); END;""",

    # R-M4 : une mesure enregistrée est immuable (traçabilité)
    "trg_mesure_immuable": """
    CREATE TRIGGER trg_mesure_immuable
    BEFORE UPDATE ON agri_mesure
    BEGIN SELECT RAISE(ABORT, 'Une mesure enregistrée ne peut pas être modifiée'); END;""",

    # R-D1 : la décision doit porter sur la zone de la mesure
    "trg_decision_zone": """
    CREATE TRIGGER trg_decision_zone
    BEFORE INSERT ON agri_decisionirrigation
    WHEN (SELECT zone_id FROM agri_mesure WHERE id = NEW.mesure_id) <> NEW.zone_id
    BEGIN SELECT RAISE(ABORT, 'Décision incohérente avec la zone de la mesure'); END;""",

    # R-D2 : mesure non VALIDE => jamais de recommandation ni d'autorisation d'arrosage
    "trg_decision_mesure_valide": """
    CREATE TRIGGER trg_decision_mesure_valide
    BEFORE INSERT ON agri_decisionirrigation
    WHEN NEW.decision IN ('ARROSAGE_RECOMMANDE','ARROSAGE_AUTORISE')
     AND (SELECT validite FROM agri_mesure WHERE id = NEW.mesure_id) <> 'VALIDE'
    BEGIN SELECT RAISE(ABORT, 'Arrosage interdit : mesure invalide'); END;""",

    # R-I1 : irrigation = décision AUTORISE, sur la même zone
    "trg_irrigation_autorisee": """
    CREATE TRIGGER trg_irrigation_autorisee
    BEFORE INSERT ON agri_irrigation
    WHEN (SELECT decision FROM agri_decisionirrigation WHERE id = NEW.decision_id)
             <> 'ARROSAGE_AUTORISE'
      OR (SELECT zone_id FROM agri_decisionirrigation WHERE id = NEW.decision_id) <> NEW.zone_id
    BEGIN SELECT RAISE(ABORT, 'Irrigation refusée : aucune autorisation valide pour cette zone'); END;""",

    # R-I2 : durée demandée <= plafond configurable
    "trg_irrigation_plafond": """
    CREATE TRIGGER trg_irrigation_plafond
    BEFORE INSERT ON agri_irrigation
    WHEN NEW.duree_max_s > (SELECT CAST(valeur AS INTEGER) FROM agri_parametresysteme
                            WHERE cle = 'pompe_duree_max_s')
    BEGIN SELECT RAISE(ABORT, 'Durée d''arrosage supérieure au plafond système'); END;""",

    # R-I3 : l'autorisation doit reposer sur une mesure récente
    "trg_irrigation_mesure_recente": """
    CREATE TRIGGER trg_irrigation_mesure_recente
    BEFORE INSERT ON agri_irrigation
    WHEN (SELECT strftime('%s','now') - strftime('%s', m.horodatage_mesure)
          FROM agri_decisionirrigation d JOIN agri_mesure m ON m.id = d.mesure_id
          WHERE d.id = NEW.decision_id)
         > (SELECT CAST(valeur AS INTEGER) FROM agri_parametresysteme WHERE cle = 'mesure_age_max_s')
    BEGIN SELECT RAISE(ABORT, 'Mesure trop ancienne pour autoriser un arrosage'); END;""",
}


def parametres_par_defaut(apps, schema_editor):
    Param = apps.get_model("agri", "ParametreSysteme")
    for cle, valeur, desc in [
        ("pompe_duree_max_s", "30", "Durée maximale absolue d'un arrosage (secondes)"),
        ("mesure_age_max_s", "600", "Âge max d'une mesure pour autoriser un arrosage (s)"),
        ("delai_confirmation_s", "120", "Délai avant de déclarer une mission NON_CONFIRMEE (s)"),
    ]:
        Param.objects.get_or_create(cle=cle, defaults={"valeur": valeur, "description": desc})


class Migration(migrations.Migration):
    dependencies = [("agri", "0001_initial")]

    operations = [
        migrations.RunSQL(sql=[sql], reverse_sql=[f"DROP TRIGGER IF EXISTS {name};"])
        for name, sql in TRIGGERS.items()
    ] + [migrations.RunPython(parametres_par_defaut, migrations.RunPython.noop)]
