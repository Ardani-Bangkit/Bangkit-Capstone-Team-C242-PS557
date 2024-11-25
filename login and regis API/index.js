import express from "express";
import dotenv from "dotenv";
import cookieParser from "cookie-parser";
import db from "./config/database.js";
import router from "./routes/index.js";
import users from "./model/user-model.js";
import cors from "cors";
dotenv.config();
const app = express();


try{
    await db.authenticate();
    console.log('Database connected..');
    //await users.sync();
}catch (error){
    console.log(error);
}

//app.use(cors({ credentials:true, origin: 'http://localhost:3000'}));
app.use(cookieParser());
app.use(express.json());
app.use(router);

app.get("/", (req, res) => {
    console.log("Response success")
    res.send("Response Success!")
})

const port = process.env.PORT || 8080;
app.listen(port, () => console.log(`Server running on port ${port}`));
