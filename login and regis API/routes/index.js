import express from "express";
import { Getuser , regis, login, logout, updateUser} from "../controller/users.js";
import { verifytoken } from "../middleware/VerifyToken.js";
import { refreshtoken } from "../controller/refereshToken.js";
const router = express.Router();

router.post('/users',regis);
router.get('/users',verifytoken,Getuser);
router.post('/login',login);
router.get('/token',refreshtoken);
router.delete('/logout',logout);
router.put('/users/:id', verifytoken, updateUser);

export default router;
