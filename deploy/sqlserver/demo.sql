-- Small demo warehouse used to exercise All-Ontology's SQL Server connector.
IF DB_ID(N'DemoWarehouse') IS NULL
BEGIN
    CREATE DATABASE DemoWarehouse;
END
GO

USE DemoWarehouse;
GO

IF SCHEMA_ID(N'sales') IS NULL
    EXEC(N'CREATE SCHEMA sales');
GO

IF OBJECT_ID(N'sales.Customers', N'U') IS NULL
BEGIN
    CREATE TABLE sales.Customers (
        CustomerID   INT           NOT NULL PRIMARY KEY,
        CustomerName NVARCHAR(120) NOT NULL,
        City         NVARCHAR(80)  NOT NULL,
        Country      NVARCHAR(80)  NOT NULL,
        SignupDate   DATE          NOT NULL
    );

    CREATE TABLE sales.Products (
        ProductID   INT            NOT NULL PRIMARY KEY,
        ProductName NVARCHAR(120)  NOT NULL,
        Category    NVARCHAR(60)   NOT NULL,
        UnitPrice   DECIMAL(10, 2) NOT NULL
    );

    CREATE TABLE sales.Orders (
        OrderID     INT            NOT NULL PRIMARY KEY,
        CustomerID  INT            NOT NULL REFERENCES sales.Customers (CustomerID),
        OrderDate   DATE           NOT NULL,
        Channel     NVARCHAR(30)   NOT NULL
    );

    CREATE TABLE sales.OrderLines (
        OrderLineID INT            NOT NULL PRIMARY KEY,
        OrderID     INT            NOT NULL REFERENCES sales.Orders (OrderID),
        ProductID   INT            NOT NULL REFERENCES sales.Products (ProductID),
        Quantity    INT            NOT NULL,
        UnitPrice   DECIMAL(10, 2) NOT NULL
    );

    INSERT INTO sales.Customers VALUES
        (1, N'Northwind Traders', N'Seattle',   N'United States', '2024-01-14'),
        (2, N'Contoso Ltd',       N'London',    N'United Kingdom', '2024-02-03'),
        (3, N'Fabrikam Inc',      N'Berlin',    N'Germany',        '2024-03-22'),
        (4, N'Wide World Importers', N'Shanghai', N'China',        '2024-05-09');

    INSERT INTO sales.Products VALUES
        (10, N'Chai Tea',        N'Beverages', 18.00),
        (20, N'Chang Beer',      N'Beverages', 19.00),
        (30, N'Aniseed Syrup',   N'Pantry',    10.00),
        (40, N'Cajun Seasoning', N'Pantry',    22.00);

    INSERT INTO sales.Orders VALUES
        (1001, 1, '2025-01-05', N'Web'),
        (1002, 2, '2025-01-19', N'Partner'),
        (1003, 1, '2025-02-02', N'Web'),
        (1004, 4, '2025-02-17', N'Retail'),
        (1005, 3, '2025-03-08', N'Web');

    INSERT INTO sales.OrderLines VALUES
        (1, 1001, 10, 12, 18.00),
        (2, 1001, 30,  4, 10.00),
        (3, 1002, 20, 24, 19.00),
        (4, 1003, 10,  6, 18.00),
        (5, 1004, 40, 10, 22.00),
        (6, 1005, 20, 48, 19.00),
        (7, 1005, 30, 12, 10.00);
END
GO
