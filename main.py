def main():
    class Model:
        class _Config:
            id = 1

    class User(Model):
        class _Config(Model._Config):
            name = "anrb"

    print(User._Config.id)


if __name__ == "__main__":
    main()
