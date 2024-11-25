import { Sequelize } from "sequelize";

const db = new Sequelize('auth_db','root','lensa',{
    host: "34.34.218.3",
    dialect:"mysql",

});

export default db;