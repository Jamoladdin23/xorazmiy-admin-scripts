"""Скрипт 1: онбординг нового сотрудника.

Создаёт пользователя, назначает руководителя, добавляет в группы отдела
и в SG-AllStaff, выводит временный пароль для передачи сотруднику.

Примеры:
  python onboard.py --first Bekzod --last Tursunov --title "Sales Manager" \
      --department Yemak --manager jamal.zaripov --groups SG-Yemak

  # сначала посмотреть, что будет сделано, ничего не создавая:
  python onboard.py --first Olena --last Shevchenko --title "Product Manager" \
      --department Reservla --manager jamal.zaripov --groups SG-Reservla --dry-run
"""
import argparse
import os
import secrets
import string
import sys
import time
import unicodedata

from graph import GRAPH, get_all, get_one, post, put

DOMAIN = os.environ.get("DOMAIN", "xorazmiy.tech")
COMPANY = "Xorazmiy Tech"
ALWAYS_GROUPS = ["SG-AllStaff"]  # в эти группы попадает каждый новый сотрудник


def ascii_slug(text: str) -> str:
    """Novák -> novak, Šťastný -> stastny: убираем диакритику для логина."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if c.isascii()).lower().replace(" ", "")


def make_password(length: int = 16) -> str:
    """Случайный пароль, который точно пройдёт политику сложности Entra."""
    alphabet = string.ascii_letters + string.digits + "!@#$%&*?"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pwd) and any(c.isupper() for c in pwd)
                and any(c.isdigit() for c in pwd) and any(c in "!@#$%&*?" for c in pwd)):
            return pwd


def find_group(name: str) -> dict:
    found = get_all("/groups", {"$filter": f"displayName eq '{name}'", "$select": "id,displayName"})
    if not found:
        sys.exit(f"Группа не найдена: {name}")
    return found[0]


def add_to_group(group: dict, user_id: str) -> None:
    body = {"@odata.id": f"{GRAPH}/directoryObjects/{user_id}"}
    # Только что созданный пользователь может быть ещё не виден во всех
    # репликах каталога — поэтому несколько попыток с паузой.
    for attempt in range(1, 6):
        try:
            post(f"/groups/{group['id']}/members/$ref", body)
            print(f"  + группа {group['displayName']}")
            return
        except RuntimeError as e:
            if "already exist" in str(e):
                print(f"  = уже в группе {group['displayName']}")
                return
            if attempt == 5:
                raise
            time.sleep(3)


def main() -> None:
    p = argparse.ArgumentParser(description="Онбординг сотрудника в Entra ID")
    p.add_argument("--first", required=True)
    p.add_argument("--last", required=True)
    p.add_argument("--title", required=True, help="должность")
    p.add_argument("--department", required=True)
    p.add_argument("--manager", help="логин руководителя без домена, напр. jamal.zaripov")
    p.add_argument("--groups", nargs="*", default=[], help="группы отдела")
    p.add_argument("--dry-run", action="store_true", help="только показать, ничего не менять")
    a = p.parse_args()

    upn = f"{ascii_slug(a.first)}.{ascii_slug(a.last)}@{DOMAIN}"
    groups = ALWAYS_GROUPS + [g for g in a.groups if g not in ALWAYS_GROUPS]

    # 1. Проверки ДО любых изменений: пользователя ещё нет, руководитель и группы есть
    if get_one(f"/users/{upn}", {"$select": "id"}):
        sys.exit(f"Пользователь уже существует: {upn}")

    manager = None
    if a.manager:
        manager_upn = a.manager if "@" in a.manager else f"{a.manager}@{DOMAIN}"
        manager = get_one(f"/users/{manager_upn}", {"$select": "id,displayName"})
        if not manager:
            sys.exit(f"Руководитель не найден: {manager_upn}")

    group_objs = [find_group(g) for g in groups]

    print(f"\nСотрудник:    {a.first} {a.last} <{upn}>")
    print(f"Должность:    {a.title}, отдел {a.department}")
    print(f"Руководитель: {manager['displayName'] if manager else '—'}")
    print(f"Группы:       {', '.join(groups)}")

    if a.dry_run:
        print("\n--dry-run: ничего не создано.")
        return

    # 2. Создание пользователя
    password = make_password()
    user = post("/users", {
        "accountEnabled": True,
        "displayName": f"{a.first} {a.last}",
        "givenName": a.first,
        "surname": a.last,
        "mailNickname": upn.split("@")[0].replace(".", ""),
        "userPrincipalName": upn,
        "jobTitle": a.title,
        "department": a.department,
        "companyName": COMPANY,
        "usageLocation": "CZ",  # без этого нельзя будет назначить лицензию
        "city": "Praha",
        "country": "Czech Republic",
        "passwordProfile": {
            "password": password,
            "forceChangePasswordNextSignIn": True,  # сотрудник сменит пароль при первом входе
        },
    })
    print(f"\n+ создан {upn}")

    # 3. Руководитель
    if manager:
        put(f"/users/{user['id']}/manager/$ref",
            {"@odata.id": f"{GRAPH}/users/{manager['id']}"})
        print(f"  + руководитель {manager['displayName']}")

    # 4. Группы
    for g in group_objs:
        add_to_group(g, user["id"])

    # 5. Данные для передачи сотруднику (пароль нигде не сохраняется)
    print("\n=== Передать сотруднику ===")
    print(f"Логин:  {upn}")
    print(f"Пароль: {password}   (временный, сменить при первом входе)")
    print("Вход:   https://myapps.microsoft.com")


if __name__ == "__main__":
    main()
