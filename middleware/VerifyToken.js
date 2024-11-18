import jwt from "jsonwebtoken";

export const verifytoken = (req, res, next) =>{
    const authheader = req.headers['authorization'];
    const token = authheader && authheader.split(' ')[1];
    if(token==null) return res.sendStatus(401);
    jwt.verify(token, process.env.ACCESS_TOKEN_SECRET,(err,decoded) => {
        if(err) return res.sendStatus(403);
        req.email = decoded.email;
        next();
    }
    )
}