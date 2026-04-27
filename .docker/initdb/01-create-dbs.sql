-- Create both development and test databases on first container initialization
-- This script runs only when PGDATA is empty (first start of the volume)
CREATE DATABASE "odoo-dev";
CREATE DATABASE "odoo-test";
