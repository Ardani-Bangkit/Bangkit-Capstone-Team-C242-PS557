import { Sequelize } from "sequelize";
import db from "../config/database.js";

const {DataTypes} = Sequelize;

const users = db.define('users',{
    fullname:{
        type: DataTypes.STRING
    },
    email:{
        type: DataTypes.STRING
    },
    password:{
        type: DataTypes.STRING
    },
    Gender:{
        type: DataTypes.STRING
    },
    DateOfBirth:{
        type: DataTypes.DATE
    },
    Adress:{
        type: DataTypes.TEXT
    },
    city:{
        type: DataTypes.STRING
    },
    postcode:{
        type: DataTypes.INTEGER
    },
    Skintype:{
        type: DataTypes.STRING
    },
    medicalhistory:{
        type: DataTypes.TEXT
    },
    alergies:{
        type: DataTypes.TEXT
    },
    medication:{
        type: DataTypes.TEXT
    },
    refresh_token:{
        type: DataTypes.TEXT
    },
},
    {
    freezeTableName:true
})

export default users;