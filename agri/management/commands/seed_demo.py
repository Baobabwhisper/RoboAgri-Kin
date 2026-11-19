from datetime import date

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from agri.models import (Capteur, Culture, DecisionIrrigation, Etalonnage, EtapeMission, Incident,
                         Irrigation, Mesure, MessageCommunication, Mission, ParametreSysteme,
                         Parcelle, Plantation, Robot, Zone)

D = DecisionIrrigation.Decision


class Command(BaseCommand):
    help = "Charge un jeu de données de démonstration cohérent."

    @transaction.atomic
    def handle(self, *args, **options):
        if Robot.objects.filter(identifiant="ROBOT-01").exists():
            self.stdout.write("Données de démo déjà chargées : rien à faire.")
            return
        now = timezone.now()

        # --- Utilisateur ---------------------------------------------------
        user, created = get_user_model().objects.get_or_create(
            username="agronome", defaults={"email": "agronome@ucc.cd"})
        if created:
            user.set_password("demo1234")
            user.save()

        # --- Référentiel agricole -----------------------------------------
        parcelle = Parcelle.objects.create(code="P01", nom="Parcelle expérimentale UCC",
                                           localisation="Kinshasa, Limete", superficie_m2=24)
        z1, z2, z3 = [Zone.objects.create(parcelle=parcelle, code=f"Z{i}", nom=f"Planche {i}",
                                          pos_x_cm=i * 100, pos_y_cm=0, seuil_min_pct=30)
                      for i in (1, 2, 3)]
        amarante = Culture.objects.create(nom="Amarante", besoin_eau=Culture.Besoin.MOYEN)
        tomate = Culture.objects.create(nom="Tomate", besoin_eau=Culture.Besoin.ELEVE)
        oignon = Culture.objects.create(nom="Oignon", besoin_eau=Culture.Besoin.FAIBLE)
        for zone, culture in ((z1, tomate), (z2, amarante), (z3, oignon)):
            Plantation.objects.create(zone=zone, culture=culture, date_debut=date(2026, 10, 1))

        # --- Matériel et étalonnage ---------------------------------------
        robot = Robot.objects.create(identifiant="ROBOT-01", nom="RoboAgri prototype",
                                     statut=Robot.Statut.DISPONIBLE)
        cap_h = Capteur.objects.create(robot=robot, type_capteur=Capteur.Type.HUMIDITE_SOL,
                                       reference="Capacitif v1.2")
        Capteur.objects.create(robot=robot, type_capteur=Capteur.Type.DISTANCE, reference="HC-SR04")
        etal = Etalonnage.objects.create(
            capteur=cap_h, brut_sec=3200, brut_humide=1400,
            methode="Lecture dans l'air (0 %) et dans l'eau (100 %), moyenne de 20 lectures.")

        def evaluer(brut):
            """Convertit le brut en % ; hors plage d'étalonnage => mesure invalide."""
            if brut > etal.brut_sec + 200 or brut < etal.brut_humide - 200:
                return None, Mesure.Validite.INVALIDE, "Valeur hors plage d'étalonnage (capteur débranché ?)"
            return round(etal.humidite_pct(brut), 1), Mesure.Validite.VALIDE, ""

        # --- Mission 1 : complète -----------------------------------------
        m1 = Mission.objects.create(robot=robot, cree_par=user)
        etapes = [EtapeMission.objects.create(mission=m1, ordre=i, zone=z)
                  for i, z in enumerate((z1, z2, z3), 1)]
        m1.statut, m1.date_debut = Mission.Statut.EN_COURS, now
        m1.save()
        robot.statut = Robot.Statut.EN_MISSION
        robot.save()

        for seq, (etape, brut) in enumerate(zip(etapes, (2900, 2000, 4095)), 1):
            pct, validite, motif = evaluer(brut)
            mesure = Mesure.objects.create(
                message_uid=f"M1-{seq:04d}", robot=robot, capteur=cap_h, etalonnage=etal,
                mission=m1, etape=etape, zone=etape.zone, numero_sequence=seq, valeur_brute=brut,
                humidite_pct=pct, validite=validite, motif_invalidite=motif, horodatage_mesure=now)
            MessageCommunication.objects.create(
                message_uid=mesure.message_uid, robot=robot, mission=m1,
                direction=MessageCommunication.Direction.ROBOT_VERS_APP, type_message="MESURE",
                payload={"zone": etape.zone.code, "brut": brut, "seq": seq})

            # Règle de décision (3 cas du sujet)
            if validite != Mesure.Validite.VALIDE:
                decision, why = D.INTERDIT, "Mesure invalide : arrosage automatique interdit"
            elif pct < etape.zone.seuil_min_pct:
                decision, why = D.AUTORISE, f"{pct} % < seuil {etape.zone.seuil_min_pct} %"
            else:
                decision, why = D.AUCUNE_ACTION, "Humidité suffisante"
            dec = DecisionIrrigation.objects.create(
                mesure=mesure, zone=etape.zone, seuil_utilise_pct=etape.zone.seuil_min_pct,
                decision=decision, motif=why)

            if decision == D.AUTORISE:
                irr = Irrigation.objects.create(
                    commande_uid="CMD-0001", decision=dec, zone=etape.zone, mission=m1, robot=robot,
                    statut=Irrigation.Statut.TERMINEE, duree_max_s=20, duree_reelle_s=18,
                    volume_ml=150, date_debut=now, date_fin=now)
            if validite != Mesure.Validite.VALIDE:
                Incident.objects.create(
                    type_incident=Incident.Type.CAPTEUR_DEFAILLANT, gravite=Incident.Gravite.CRITIQUE,
                    robot=robot, mission=m1, zone=etape.zone, mesure=mesure,
                    description="Valeur brute 4095 : capteur d'humidité probablement débranché.")
            etape.statut = (EtapeMission.Statut.FAITE if validite == Mesure.Validite.VALIDE
                            else EtapeMission.Statut.ECHEC)
            etape.date_fin = now
            etape.save()

        m1.statut, m1.date_fin = Mission.Statut.TERMINEE, now
        m1.save()

        # --- Mission 2 : coupure Wi-Fi => non confirmée ------------------
        m2 = Mission.objects.create(robot=robot, cree_par=user)
        EtapeMission.objects.create(mission=m2, ordre=1, zone=z1)
        m2.statut, m2.date_debut = Mission.Statut.EN_COURS, now
        m2.save()
        m2.statut, m2.motif_fin = Mission.Statut.NON_CONFIRMEE, "Perte de communication Wi-Fi"
        m2.save()
        Incident.objects.create(
            type_incident=Incident.Type.MISSION_NON_CONFIRMEE, robot=robot, mission=m2,
            description="Aucun accusé de réception du robot après le délai de confirmation.")

        robot.statut = Robot.Statut.DISPONIBLE
        robot.save()
        self.stdout.write(self.style.SUCCESS(
            "Démo chargée : 1 parcelle, 3 zones, 2 missions, 3 mesures, 1 irrigation, 2 incidents. "
            "Compte : agronome / demo1234"))
