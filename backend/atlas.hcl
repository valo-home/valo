data "external_schema" "sqlalchemy" {
  program = ["uv", "run", "--no-sync", "atlas-provider-sqlalchemy", "--path", "./src/app/db/models", "--dialect", "postgresql"]
}

env "main" {
  src = data.external_schema.sqlalchemy.url
  dev = getenv("ATLAS_DEV_URL")
  url = getenv("ATLAS_DB_URL")
  migration {
    dir = "file://migrations"
  }
}
